<!--
THIS FILE IS AUTOGENERATED BY README.ipynb.
Ideally you should edit README.ipynb and use 'generate-readme' to produce README.md. 
But it's okay to edit README.md too directly if you want to fix something -- I can run generate-readme myself later.
-->


# What is Cachew?
TLDR: cachew lets you **cache function calls** into an sqlite database on your disk in a matter of **single decorator** (similar to [functools.lru_cache](https://docs.python.org/3/library/functools.html#functools.lru_cache)). The difference from `functools.lru_cache` is that cached data is persisted between program runs, so next time you call your function, it will only be a matter of reading from the cache.
Cache is **invalidated automatically** if your function's arguments change, so you don't have to think about maintaining it.

In order to be cacheable, your function needs to return a simple data type, or an [Iterator](https://docs.python.org/3/library/typing.html#typing.Iterator) over such types.

A simple type is defined as:

- primitive: `str`/`int`/`float`/`bool`
- JSON-like types (`dict`/`list`/`tuple`)
- `datetime`
- `Exception` (useful for [error handling](https://beepb00p.xyz/mypy-error-handling.html#kiss) )
- [NamedTuples](https://docs.python.org/3/library/typing.html#typing.NamedTuple)
- [dataclasses](https://docs.python.org/3/library/dataclasses.html)


That allows to **automatically infer schema from type hints** ([PEP 526](https://www.python.org/dev/peps/pep-0526)) and not think about serializing/deserializing.
Thanks to type hints, you don't need to annotate your classes with any special decorators, inherit from some special base classes, etc., as it's often the case for serialization libraries.

## Motivation

I often find myself processing big chunks of data, merging data together, computing some aggregates on it or extracting few bits I'm interested at. While I'm trying to utilize REPL as much as I can, some things are still fragile and often you just have to rerun the whole thing in the process of development. This can be frustrating if data parsing and processing takes seconds, let alone minutes in some cases.

Conventional way of dealing with it is serializing results along with some sort of hash (e.g. md5) of input files,
comparing on the next run and returning cached data if nothing changed.

Simple as it sounds, it is pretty tedious to do every time you need to memorize some data, contaminates your code with routine and distracts you from your main task.


# Examples
## Processing Wikipedia
Imagine you're working on a data analysis pipeline for some huge dataset, say, extracting urls and their titles from Wikipedia archive.
Parsing it (`extract_links` function) takes hours, however, as long as the archive is same you will always get same results. So it would be nice to be able to cache the results somehow.


With this library your can achieve it through single `@cachew` decorator.


```python
>>> from typing import NamedTuple, Iterator
>>> class Link(NamedTuple):
...     url : str
...     text: str
...
>>> @cachew
... def extract_links(archive_path: str) -> Iterator[Link]:
...     for i in range(5):
...         # simulate slow IO
...         # this function runs for five seconds for the purpose of demonstration, but realistically it might take hours
...         import time; time.sleep(1)
...         yield Link(url=f'http://link{i}.org', text=f'text {i}')
...
>>> list(extract_links(archive_path='wikipedia_20190830.zip')) # that would take about 5 seconds on first run
[Link(url='http://link0.org', text='text 0'), Link(url='http://link1.org', text='text 1'), Link(url='http://link2.org', text='text 2'), Link(url='http://link3.org', text='text 3'), Link(url='http://link4.org', text='text 4')]

>>> from timeit import Timer
>>> res = Timer(lambda: list(extract_links(archive_path='wikipedia_20190830.zip'))).timeit(number=1)
... # second run is cached, so should take less time
>>> print(f"call took {int(res)} seconds")
call took 0 seconds

>>> res = Timer(lambda: list(extract_links(archive_path='wikipedia_20200101.zip'))).timeit(number=1)
... # now file has changed, so the cache will be discarded
>>> print(f"call took {int(res)} seconds")
call took 5 seconds
```


When you call `extract_links` with the same archive, you start getting results in a matter of milliseconds, as fast as sqlite reads it.

When you use newer archive, `archive_path` changes, which will make cachew invalidate old cache and recompute it, so you don't need to think about maintaining it separately.

## Incremental data exports
This is my most common usecase of cachew, which I'll illustrate with example.

I'm using an [environment sensor](https://bluemaestro.com/products/product-details/bluetooth-environmental-monitor-and-logger) to log stats about temperature and humidity.
Data is synchronized via bluetooth in the sqlite database, which is easy to access. However sensor has limited memory (e.g. 1000 latest measurements).
That means that I end up with a new database every few days, each of them containing only a slice of data I need, e.g.:

    ...
    20190715100026.db
    20190716100138.db
    20190717101651.db
    20190718100118.db
    20190719100701.db
    ...

To access **all** of historic temperature data, I have two options:

- Go through all the data chunks every time I wan to access them and 'merge' into a unified stream of measurements, e.g. something like:
  
      def measurements(chunks: List[Path]) -> Iterator[Measurement]:
          for chunk in chunks:
              # read measurements from 'chunk' and yield unseen ones

  This is very **easy, but slow** and you waste CPU for no reason every time you need data.

- Keep a 'master' database and write code to merge chunks in it.

  This is very **efficient, but tedious**:
  
  - requires serializing/deserializing data -- boilerplate
  - requires manually managing sqlite database -- error prone, hard to get right every time
  - requires careful scheduling, ideally you want to access new data without having to refresh cache

  
Cachew gives the best of two worlds and makes it both **easy and efficient**. The only thing you have to do is to decorate your function:

    @cachew      
    def measurements(chunks: List[Path]) -> Iterator[Measurement]:
        # ...
        
- as long as `chunks` stay same, data stays same so you always read from sqlite cache which is very fast
- you don't need to maintain the database, cache is automatically refreshed when `chunks` change (i.e. you got new data)

  All the complexity of handling database is hidden in `cachew` implementation.


# How it works

- first your objects get [converted](src/cachew/marshall/cachew.py#L34) into a simpler JSON-like representation 
- after that, they are mapped into byte blobs via [`orjson`](https://github.com/ijl/orjson).

When the function is called, cachew [computes the hash of your function's arguments ](src/cachew/__init__.py:#L503)
and compares it against the previously stored hash value.
    
- If they match, it would deserialize and yield whatever is stored in the cache database
- If the hash mismatches, the original function is called and new data is stored along with the new hash



# Features



* automatic schema inference: [1](src/cachew/tests/test_cachew.py#L349), [2](src/cachew/tests/test_cachew.py#L363)
* supported types:    

    * primitive: `str`, `int`, `float`, `bool`, `datetime`, `date`, `Exception`
    
      See [tests.test_types](src/cachew/tests/test_cachew.py#L675), [tests.test_primitive](src/cachew/tests/test_cachew.py#L709), [tests.test_dates](src/cachew/tests/test_cachew.py#L629), [tests.test_exceptions](src/cachew/tests/test_cachew.py#L1036)
    * [@dataclass and NamedTuple](src/cachew/tests/test_cachew.py#L591)
    * [Optional](src/cachew/tests/test_cachew.py#L493) types
    * [Union](src/cachew/tests/test_cachew.py#L787) types
    * [nested datatypes](src/cachew/tests/test_cachew.py#L409)
    
* detects [datatype schema changes](src/cachew/tests/test_cachew.py#L439) and discards old data automatically


# Performance
Updating cache takes certain overhead, but that would depend on how complicated your datatype in the first place, so I'd suggest measuring if you're not sure.

During reading cache all that happens is reading blobls from sqlite/decoding as JSON, and mapping them onto your target datatype, so the overhead depends on each of these steps.

It would almost certainly make your program faster if your computations take more than several seconds.

You can find some of my performance tests in [benchmarks/](benchmarks) dir, and the tests themselves in [src/cachew/tests/marshall.py](src/cachew/tests/marshall.py).


# Using
See [docstring](src/cachew/__init__.py#L328) for up-to-date documentation on parameters and return types. 
You can also use [extensive unit tests](src/cachew/tests/test_cachew.py) as a reference.
    
Some useful (but optional) arguments of `@cachew` decorator:
    
* `cache_path` can be a directory, or a callable that [returns a path](src/cachew/tests/test_cachew.py#L386) and depends on function's arguments.
    
   By default, `settings.DEFAULT_CACHEW_DIR` is used.
    
* `depends_on` is a function which determines whether your inputs have changed, and the cache needs to be invalidated.
    
   By default it just uses string representation of the arguments, you can also specify a custom callable.
    
   For instance, it can be used to [discard cache](src/cachew/tests/test_cachew.py#L89) if the input file was modified.
    
* `cls` is the type that would be serialized.

   By default, it is inferred from return type annotations, but can be specified explicitly if you don't control the code you want to cache.


# Installing
Package is available on [pypi](https://pypi.org/project/cachew/).

    pip3 install --user cachew
    
## Developing
I'm using [tox](tox.ini) to run tests, and [Github Actions](.github/workflows/main.yml) for CI.

# Implementation

* why NamedTuples and dataclasses?
  
  `NamedTuple` and `dataclass` provide a very straightforward and self documenting way to represent data in Python.
  Very compact syntax makes it extremely convenient even for one-off means of communicating between couple of functions.
   
  If you want to find out more why you should use more dataclasses in your code I suggest these links:
  
  - [What are data classes?](https://stackoverflow.com/questions/47955263/what-are-data-classes-and-how-are-they-different-from-common-classes)
  - [basic data classes](https://realpython.com/python-data-classes/#basic-data-classes)
   
* why not `pandas.DataFrame`?

  DataFrames are great and can be serialised to csv or pickled.
  They are good to have as one of the ways you can interface with your data, however hardly convenient to think about it abstractly due to their dynamic nature.
  They also can't be nested.

* why not [ORM](https://en.wikipedia.org/wiki/Object-relational_mapping)?
  
  ORMs tend to be pretty invasive, which might complicate your scripts or even ruin performance. It's also somewhat an overkill for such a specific purpose.

  * E.g. [SQLAlchemy](https://docs.sqlalchemy.org/en/13/orm/tutorial.html#declare-a-mapping) requires you using custom sqlalchemy specific types and inheriting a base class.
    Also it doesn't support nested types.
    
* why not [pickle](https://docs.python.org/3/library/pickle.html) or [`marshmallow`](https://marshmallow.readthedocs.io/en/3.0/nesting.html) or `pydantic`?

  Pickling is kinda heavyweigh for plain data class, it's slower just using JSON. Lastly, it can only be loaded via Python, whereas JSON + sqlite has numerous bindings and tools to explore and interface.

  Marshmallow is a common way to map data into db-friendly format, but it requires explicit schema which is an overhead when you have it already in the form of type annotations. I've looked at existing projects to utilize type annotations, but didn't find them covering all I wanted:
  
  * https://marshmallow-annotations.readthedocs.io/en/latest/ext/namedtuple.html#namedtuple-type-api
  * https://pypi.org/project/marshmallow-dataclass
 
  I wrote up an extensive review of alternatives I considered: see [doc/serialization.org](doc/serialization.org).
  So far looks like only `cattrs` comes somewhere close to the feature set I need, but still not quite.

* why `sqlite` database for storage?

  It's pretty efficient and iterables (i.e. sequences) map onto database rows in a very straightforward manner.
  That said it would be interesting to experiment with alternative storages, e.g. in-RAM or distributed like Redis.


# Tips and tricks
## Optional dependency
You can benefit from `cachew` even if you don't want to bloat your app's dependencies. Just use the following snippet:


```python
def mcachew(*args, **kwargs):
    """
    Stands for 'Maybe cachew'.
    Defensive wrapper around @cachew to make it an optional dependency.
    """
    try:
        import cachew
    except ModuleNotFoundError:
        import warnings
        warnings.warn('cachew library not found. You might want to install it to speed things up. See https://github.com/karlicoss/cachew')
        return lambda orig_func: orig_func
    else:
        return cachew.cachew(*args, **kwargs)

```


Now you can use `@mcachew` in place of `@cachew`, and be certain things don't break if `cachew` is missing.

## Settings


[cachew.settings](src/cachew/__init__.py#L67) exposes some parameters that allow you to control `cachew` behaviour:
- `ENABLE`: set to `False` if you want to disable caching for without removing the decorators (useful for testing and debugging).
   You can also use [cachew.extra.disabled_cachew](src/cachew/extra.py#L18) context manager to do it temporarily.
- `DEFAULT_CACHEW_DIR`: override to set a different base directory. The default is the "user cache directory" (see [appdirs docs](https://github.com/ActiveState/appdirs#some-example-output)).
- `THROW_ON_ERROR`: by default, cachew is defensive and simply attemps to cause the original function on caching issues.
   Set to `True` to catch errors earlier.


## Updating this readme
This is a literate readme, implemented as a Jupiter notebook: [README.ipynb](README.ipynb). To update the (autogenerated) [README.md](README.md), use [generate-readme](generate-readme) script.
