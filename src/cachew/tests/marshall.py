from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import (
    Literal,
)

import orjson
import pytest
import pytz

from ..marshall.common import Json
from ..marshall.cachew import CachewMarshall
from .utils import (
    gc_control,
    profile,
    running_on_ci,
    timer,
)


Impl = Literal[
    'cachew',  # our custom deserialization
    'cattrs',
]
Impl_members = Impl.__args__  # type: ignore[attr-defined]


def do_test(*, test_name: str, Type, factory, count: int, impl: Impl = 'cachew') -> None:
    if count > 100 and running_on_ci:
        pytest.skip("test too heavy for CI, only meant to run manually")

    if impl == 'cachew':
        marshall = CachewMarshall(Type_=Type)
        to_json = marshall.dump
        from_json = marshall.load

    elif impl == 'cattrs':
        from cattrs import Converter
        from cattrs.strategies import configure_tagged_union

        converter = Converter()

        from typing import get_args, get_origin
        from typing import Union
        import types

        def is_union(type_) -> bool:
            origin = get_origin(type_)
            return origin is Union or origin is types.UnionType

        def union_structure_hook_factory(_):
            def union_hook(data, type_):
                args = get_args(type_)

                if data is None:  # we don't try to coerce None into anything
                    return None

                for t in args:
                    try:
                        res = converter.structure(data, t)
                        print("YAY", data, t)
                        return res
                    except Exception:
                        continue
                raise ValueError(f"Could not cast {data} to {type_}")

            return union_hook

        # borrowed from https://github.com/python-attrs/cattrs/issues/423
        # uhh, this doesn't really work straightaway...
        # likely need to combine what cattr does with configure_tagged_union
        # converter.register_structure_hook_factory(is_union, union_structure_hook_factory)
        # configure_tagged_union(
        #     union=Type,
        #     converter=converter,
        # )
        # NOTE: this seems to give a bit of speedup... maybe raise an issue or something?
        # fmt: off
        unstruct_func = converter._unstructure_func.dispatch(Type)  # about 20% speedup
        struct_func   = converter._structure_func  .dispatch(Type)  # TODO speedup
        # fmt: on

        to_json = unstruct_func  # type: ignore[assignment]
        # todo would be nice to use partial? but how do we bind a positional arg?
        from_json = lambda x: struct_func(x, Type)
    else:
        assert False

    print('', file=sys.stderr)  # kinda annoying, pytest starts printing on the same line as test name

    with profile(test_name + ':baseline'), timer(f'building      {count} objects of type {Type}'):
        objects = list(factory(count=count))

    jsons: list[Json] = [None for _ in range(count)]
    with profile(test_name + ':serialize'), timer(f'serializing   {count} objects of type {Type}'):
        for i in range(count):
            jsons[i] = to_json(objects[i])

    strs: list[bytes] = [None for _ in range(count)]  # type: ignore
    with profile(test_name + ':json_dump'), timer(f'json dump     {count} objects of type {Type}'):
        for i in range(count):
            # TODO any orjson options to speed up?
            strs[i] = orjson.dumps(jsons[i])  # pylint: disable=no-member

    db = Path('/tmp/cachew_test/db.sqlite')
    if db.parent.exists():
        shutil.rmtree(db.parent)
    db.parent.mkdir()

    with profile(test_name + ':sqlite_dump'), timer(f'sqlite dump   {count} objects of type {Type}'):
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE data (value BLOB)')
            conn.executemany('INSERT INTO data (value) VALUES (?)', [(s,) for s in strs])
        conn.close()

    strs2: list[bytes] = [None for _ in range(count)]  # type: ignore
    with profile(test_name + ':sqlite_load'), timer(f'sqlite load   {count} objects of type {Type}'):
        with sqlite3.connect(db) as conn:
            i = 0
            for (value,) in conn.execute('SELECT value FROM data'):
                strs2[i] = value
                i += 1
        conn.close()

    cache = db.parent / 'cache.jsonl'

    with profile(test_name + ':jsonl_dump'), timer(f'jsonl dump    {count} objects of type {Type}'):
        with cache.open('wb') as fw:
            for s in strs:
                fw.write(s + b'\n')

    strs3: list[bytes] = [None for _ in range(count)]  # type: ignore
    with profile(test_name + ':jsonl_load'), timer(f'jsonl load    {count} objects of type {Type}'):
        i = 0
        with cache.open('rb') as fr:
            for l in fr:
                l = l.rstrip(b'\n')
                strs3[i] = l
                i += 1

    assert strs2[:100] + strs2[-100:] == strs3[:100] + strs3[-100:]  # just in case

    jsons2: list[Json] = [None for _ in range(count)]
    with profile(test_name + ':json_load'), timer(f'json load     {count} objects of type {Type}'):
        for i in range(count):
            # TODO any orjson options to speed up?
            jsons2[i] = orjson.loads(strs2[i])  # pylint: disable=no-member

    objects2 = [None for _ in range(count)]
    with profile(test_name + ':deserialize'), timer(f'deserializing {count} objects of type {Type}'):
        for i in range(count):
            objects2[i] = from_json(jsons2[i])

    assert objects == objects2


@dataclass
class Name:
    first: str
    last: str


@pytest.mark.parametrize('impl', Impl_members)
@pytest.mark.parametrize('count', [99, 1_000_000, 5_000_000])
@pytest.mark.parametrize('gc_on', [True, False], ids=['gc_on', 'gc_off'])
def test_union_str_dataclass(impl: Impl, count: int, gc_control, request) -> None:
    # NOTE: previously was union_str_namedtuple, but adapted to work with cattrs for now
    # perf difference between datacalss/namedtuple here seems negligible so old benchmark results should apply

    if impl == 'cattrs':
        pytest.skip('TODO need to adjust the handling of Union types..')

    def factory(count: int):
        objects: list[str | Name] = []
        for i in range(count):
            if i % 2 == 0:
                objects.append(str(i))
            else:
                objects.append(Name(first=f'first {i}', last=f'last {i}'))
        return objects

    do_test(test_name=request.node.name, Type=str | Name, factory=factory, count=count, impl=impl)


# OK, performance with calling this manually (not via pytest) is the same
# do_test_union_str_dataclass(count=1_000_000, test_name='adhoc')


@pytest.mark.parametrize('impl', Impl_members)
@pytest.mark.parametrize('count', [99, 1_000_000, 5_000_000])
@pytest.mark.parametrize('gc_on', [True, False], ids=['gc_on', 'gc_off'])
def test_datetimes(impl: Impl, count: int, gc_control, request) -> None:
    if impl == 'cattrs':
        pytest.skip('TODO support datetime with pytz for cattrs')

    def factory(*, count: int):
        tzs = [
            pytz.timezone('Europe/Berlin'),
            timezone.utc,
            pytz.timezone('America/New_York'),
        ]
        start = datetime.fromisoformat('1990-01-01T00:00:00')
        end = datetime.fromisoformat('2030-01-01T00:00:00')
        step = (end - start) / count
        for i in range(count):
            dt = start + step * i
            tz = tzs[i % len(tzs)]
            yield dt.replace(tzinfo=tz)

    do_test(test_name=request.node.name, Type=datetime, factory=factory, count=count, impl=impl)


@pytest.mark.parametrize('impl', Impl_members)
@pytest.mark.parametrize('count', [99, 1_000_000])
@pytest.mark.parametrize('gc_on', [True, False], ids=['gc_on', 'gc_off'])
def test_many_from_cachew(impl: Impl, count: int, gc_control, request) -> None:
    @dataclass
    class UUU:
        xx: int
        yy: int

    @dataclass
    class TE2:
        value: int
        uuu: UUU
        value2: int

    def factory(*, count: int):
        for i in range(count):
            yield TE2(value=i, uuu=UUU(xx=i, yy=i), value2=i)

    do_test(test_name=request.node.name, Type=TE2, factory=factory, count=count, impl=impl)


# TODO next test should probs be runtimeerror?