"""
SQLAlchemy + SQLite does not support the autoincrement feature for BigInteger columns.
This file provides a class as a workaround for this problem:
It uses a normal Integer column in SQLite and a BigInteger column otherwise.
SQLite Integer columns can autoincrement, but they are limited to 2^63-1.
See https://stackoverflow.com/a/23175518/4306257 for more information.
"""

from sqlalchemy import BigInteger
from sqlalchemy.dialects import postgresql, mysql, sqlite

# Solution from https://stackoverflow.com/a/23175518/4306257
BigIntegerWithAutoincrement = BigInteger()
BigIntegerWithAutoincrement = BigIntegerWithAutoincrement.with_variant(postgresql.BIGINT(), 'postgresql')
BigIntegerWithAutoincrement = BigIntegerWithAutoincrement.with_variant(mysql.BIGINT(), 'mysql')
BigIntegerWithAutoincrement = BigIntegerWithAutoincrement.with_variant(sqlite.INTEGER(), 'sqlite')