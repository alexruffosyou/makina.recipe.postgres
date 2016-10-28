Introduction
============

This package is a buildout recipe to generate scripts for accessing
and controling a whole postgres server, optionally initializing a database
using the initdb command.

How to use
==========

EXAMPLE (postgis init)::

        parts =
            ...
            initdb

        [initdb]
        recipe = makina.recipe.postgres
        bin = ${buildout:directory}/parts/postgresql/bin
        initdb = true
        pgdata = ${buildout:directory}/var/postgres
        port = 5433
        cmds =
            createuser --createdb    --no-createrole --no-superuser --login admin
            createuser --no-createdb --no-createrole --no-superuser --login zope
            createdb --owner admin --encoding LATIN9 zsig
            createlang plpgsql zsig
            psql -d zsig -f ${buildout:directory}/parts/postgis/share/lwpostgis.sql
            psql -d zsig -f ${buildout:directory}/parts/postgis/share/spatial_ref_sys.sql


The ``bin`` option can point to a pre-installed postgresql server location (where all postgresql system binaries are) if you don't want to install postgres with buildout, i.e.:

  * ``/usr/lib/postgresql/9.6/bin``
