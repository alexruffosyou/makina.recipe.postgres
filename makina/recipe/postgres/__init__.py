# -*- coding: utf-8 -*-
# Copyright (C)2007 'jeanmichel FRANCOIS'

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; see the file COPYING. If not, write to the
# Free Software Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
"""Recipe postgres"""
import logging
import os
import time
import re
from subprocess import check_call, call, CalledProcessError

from zc.buildout import UserError

pg_server_env = "PGDATA={self.pgdata!r}"

pg_server_command_template = """#!/bin/bash
{self.pg_server_env} exec {self.pg_bin_dir!r}/{command} "$@"
"""

pg_client_env = "PGHOST={self.socket_dir!r} PGPORT={self.port}"

pg_client_command_template = """#!/bin/bash
{self.pg_client_env} exec {self.pg_bin_dir!r}/{command} "$@"
"""

pg_shift_command_template = """#!/bin/bash
read -r -d '' USAGE <<EOM
Usage:

$0 <command> [args ...]
EOM

if [[ $# -eq 0 ]]; then
	echo $USAGE
	exit 1
fi
command=$1
shift
{env} exec {self.pg_bin_dir!r}/$command "$@"
"""

pg_command_template_map = {
    pg_server_command_template: [
        "pg_ctl",
        "postgres",
    ],
    pg_client_command_template: [
        "psql",
        "pg_isready",
    ],
}


CONFIG_PREFIX = "config."


class Recipe(object):
    """This recipe is used by zc.buildout"""

    local_conf_filename = 'postgresql.local.conf'
    include_local_conf = "include = '{}'".format(local_conf_filename)
    include_re = re.compile(r"^" + re.escape(include_local_conf))
    # silence PyLint on missing attributes:
    bin_pg_ctl = bin_pg_isready = ""

    def __init__(self, buildout, name, options):
        """options:

          - bin : path to bin folder that contains postgres binaries
          - pgdata : path to the folder that will contain postgres data
          - port : port on wich postgres is started and listen
          - initdb : specify the argument to pass to the initdb command
                     or just `true`, which defaults to:
                     `--auth-local=trust --pgdata=${:pgdata}`
          - cmds : list of psql cmd to execute after all those init

        """
        self.buildout, self.name, self.options = buildout, name, options
        if options.get('location') is None:
            options['location'] = options['prefix'] = os.path.join(
                buildout['buildout']['parts-directory'],
                name)

        # mandatory options
        try:
            self.pgdata = options['pgdata']
            self.pg_bin_dir = options['bin']
        except KeyError as e:
            raise UserError("Missing option in [%s]: %s" % (name, e))

        # options with defaults
        self.bin_dir = options.setdefault(
            "bin-directory",
            # buildout is empty on uninstall, but options should have
            # bin-directory already set in this case
            buildout.get('buildout', {}).get('bin-directory', 'bin'),

        )
        self.socket_dir = options.get('socket_dir', self.pgdata)
        self.port = options.get('port')
        options.setdefault(
            CONFIG_PREFIX + "unix_socket_directories",
            "'%s'" % self.socket_dir,
        )
        options.setdefault(CONFIG_PREFIX + "unix_socket_permissions", "0700")
        options.setdefault(CONFIG_PREFIX + "listen_addresses", "''")

        if self.port is not None:
            # non-default port, add to server config file.
            self.options[CONFIG_PREFIX + "port"] = self.port
        else:
            # default port. Needed by pg_client_command_template
            # FIXME: Can we get the compiled-in default somehow? maybe call
            # out to postgres with an empty config file...
            # or make the client env dynamic
            options['port'] = self.port = '5432'

        if options.get('initdb', '').lower() == 'true':
            options['initdb'] = "--auth-local=trust --pgdata=" + self.pgdata

        self.cmds = self.options.get('cmds', '').strip()

        self.logger = logging.getLogger(self.name)
        self.pg_server_env = pg_server_env.format(self=self)
        self.pg_client_env = pg_client_env.format(self=self)

    def pgdata_exists(self):
        return os.path.exists(self.pgdata)

    def install(self):
        """installer and updater"""
        self.create_bin_scripts()
        if not os.path.exists(self.options['location']):
            os.mkdir(self.options['location'])
        # Don't touch an existing database
        if self.pgdata_exists():
            self.configure()
            return self.options['location']
        self.initdb()
        self.configure()
        self.startdb()
        self.do_cmds()
        self.stopdb()
        return self.options['location']

    update = install

    def startdb(self):
        if self.is_db_started():
            check_call([self.bin_pg_ctl, 'restart'])
        else:
            check_call([self.bin_pg_ctl, 'start'])
        # Wait up to 10 secs for the server to run
        for _ in range(10):
            if self.is_db_listening():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Failed to start postgres")

    def stopdb(self):
        if self.is_db_started():
            check_call([self.bin_pg_ctl, 'stop'])
            time.sleep(4)

    def is_db_started(self):
        PIDFILE = os.path.join(self.pgdata, 'postmaster.pid')
        return os.path.exists(PIDFILE)

    def is_db_listening(self):
        try:
            check_call([self.bin_pg_isready])
            return True
        except CalledProcessError:
            return False

    def create_bin_scripts(self):
        # Create wrapper scripts for specific client and server commands
        for template, commands in pg_command_template_map.items():
            for command in commands:
                code = template.format(self=self, command=command)
                self.create_bin_script(command, code)
        # Create wrapper scripts for generic client and server commands
        for suffix, env in [
                ('server', self.pg_server_env),
                ('client', self.pg_client_env),
            ]:
            code = pg_shift_command_template.format(self=self, env=env)
            self.create_bin_script(self.name + "_" + suffix, code)

    def create_bin_script(self, command, code):
        path = os.path.join(self.bin_dir, command)
        with open(path, 'w') as script:
            script.write(code)
            os.chmod(path, 0755)
            # other methods might need this command:
            setattr(self, "bin_" + command, path)
            # other buildout parts might need this command:
            self.options[command] = path

    def initdb(self):
        initdb_options = self.options.get('initdb', None)
        if initdb_options and not self.pgdata_exists():
            initdb = os.path.join(self.pg_bin_dir, 'initdb')
            check_call('%s %s' % (initdb, initdb_options), shell=True)

    def configure(self):
        conf_dir = self.pgdata

        # include local configuration file
        conf_file = os.path.join(conf_dir, 'postgresql.conf')
        with open(conf_file) as f:
            conf = f.read()
        if not self.include_re.search(conf):
            self.logger.info("including local configuration")
            conf += "\n\n%s\n" % self.include_local_conf
            with open(conf_file, 'w') as f:
                f.write(conf)

        # Write local configuration file:
        local_conf = "\n".join(
            "{name} = {value}".format(
                name=name.split(".", 1)[1],
                value=self.options[name],
            )
            for name in sorted(self.options.keys())
            if name.startswith(CONFIG_PREFIX)
        )
        with open(os.path.join(conf_dir, self.local_conf_filename), "w") as f:
            self.logger.info("Writing local configuration")
            f.write(local_conf)

    def do_cmds(self):
        if not self.cmds:
            return None
        cmds = self.cmds.split(os.linesep)

        env = dict(PGHOST=self.socket_dir, PGPORT=self.port)
        for cmd in cmds:
            if not cmd:
                continue
            cmd = ['%s/%s' % (self.pg_bin_dir, cmd)]
            self.logger.info(
                "running command: %s with additional env %s", cmd, env,
            )
            call(cmd, shell=True, env=dict(os.environ, **env))


def uninstall(name, options):
    Recipe({}, name, options).stopdb()
