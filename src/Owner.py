#!/usr/bin/env python

###
# Copyright (c) 2002, Jeremiah Fincher
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

"""
Provides commands useful to the owner of the bot; the commands here require
their caller to have the 'owner' capability.  This plugin is loaded by default.
"""

import fix

import gc
import os
import imp
import sys
import linecache

import conf
import debug
import utils
import world
import ircdb
import irclib
import ircmsgs
import drivers
import privmsgs
import callbacks

def loadPluginModule(name):
    """Loads (and returns) the module for the plugin with the given name."""
    files = []
    for dir in conf.pluginDirs:
        files.extend(os.listdir(dir))
    loweredFiles = map(str.lower, files)
    try:
        index = map(str.lower, files).index(name.lower()+'.py')
        name = os.path.splitext(files[index])[0]
    except ValueError: # We'd rather raise the ImportError, so we'll let go...
        pass
    moduleInfo = imp.find_module(name, conf.pluginDirs)
    module = imp.load_module(name, *moduleInfo)
    linecache.checkcache()
    return module

def loadPluginClass(irc, module):
    """Loads the plugin Class from the given module into the given irc."""
    callback = module.Class()
    irc.addCallback(callback)
    if hasattr(callback, 'configure'):
        callback.configure(irc)

class Owner(privmsgs.CapabilityCheckingPrivmsg):
    priority = ~sys.maxint # This must be first!
    capability = 'owner'
    def __init__(self):
        callbacks.Privmsg.__init__(self)
        setattr(self.__class__, 'exec', self.__class__._exec)

    def eval(self, irc, msg, args):
        """<expression>

        Evaluates <expression> and returns its value.
        """
        if conf.allowEval:
            s = privmsgs.getArgs(args)
            try:
                irc.reply(msg, repr(eval(s)))
            except SyntaxError, e:
                irc.reply(msg, '%s: %r' % (debug.exnToString(e), s))
            except Exception, e:
                irc.reply(msg, debug.exnToString(e))
        else:
            irc.error(msg, conf.replyEvalNotAllowed)

    def _exec(self, irc, msg, args):
        """<statement>

        Execs <code>.  Returns success if it didn't raise any exceptions.
        """
        if conf.allowEval:
            s = privmsgs.getArgs(args)
            try:
                exec s
                irc.reply(msg, conf.replySuccess)
            except Exception, e:
                irc.reply(msg, debug.exnToString(e))
        else:
            irc.error(msg, conf.replyEvalNotAllowed)

    def setconf(self, irc, msg, args):
        """[<name> [<value>]]

        Lists adjustable variables in the conf-module by default, shows the
        variable type with only the <name> argument and sets the value of the
        variable to <value> when both arguments are given.
        """
        (name, value) = privmsgs.getArgs(args, needed=0, optional=2)
        if name and value:
            if conf.allowEval:
                try:
                    value = eval(value)
                except Exception, e:
                    irc.error(msg, debug.exnToString(e))
                    return
                setattr(conf, name, value)
                irc.reply(msg, conf.replySuccess)
            else:
                if name == 'allowEval':
                    irc.error(msg, 'You can\'t set the value of allowEval.')
                    return
                elif name not in conf.types:
                    irc.error(msg, 'I can\'t set that conf variable.')
                    return
                else:
                    converter = conf.types[name]
                    try:
                        value = converter(value)
                    except ValueError, e:
                        irc.error(msg, str(e))
                        return
                    setattr(conf, name, value)
                    irc.reply(msg, conf.replySuccess)
        elif name:
            typetable = {'mystr': 'string',
            'mybool': 'boolean',
            'float': 'float'}
            
            try:
                vtype = conf.types[name].__name__
            except KeyError:
                irc.error(msg, 'That conf variable doesn\'t exist.')
                return
            try:
                irc.reply(msg, '%s is a %s.' % (name, typetable[vtype]))
            except KeyError:
                irc.error(msg, '%s is of an unknown type.' % name)
        else:
            options = conf.types.keys()
            options.sort()
            irc.reply(msg, ', '.join(options))

    def setdefaultcapability(self, irc, msg, args):
        """<capability>

        Sets the default capability to be allowed for any command.
        """
        capability = callbacks.canonicalName(privmsgs.getArgs(args))
        conf.defaultCapabilities.add(capability)
        irc.reply(msg, conf.replySuccess)

    def unsetdefaultcapability(self, irc, msg, args):
        """<capability>

        Unsets the default capability for any command.
        """
        capability = callbacks.canonicalName(privmsgs.getArgs(args))
        conf.defaultCapabilities.remove(capability)
        irc.reply(msg, conf.replySuccess)

    def settrace(self, irc, msg, args):
        """takes no arguments

        Starts the function-tracing debug mode; beware that this makes *huge*
        logfiles.
        """
        sys.settrace(debug.tracer)
        irc.reply(msg, conf.replySuccess)

    def unsettrace(self, irc, msg, args):
        """takes no arguments

        Stops the function-tracing debug mode."""
        sys.settrace(None)
        irc.reply(msg, conf.replySuccess)

    def ircquote(self, irc, msg, args):
        """<string to be sent to the server>

        Sends the raw string given to the server.
        """
        s = privmsgs.getArgs(args)
        try:
            m = ircmsgs.IrcMsg(s)
            irc.queueMsg(m)
        except Exception:
            debug.recoverableException()
            irc.error(msg, conf.replyError)

    def quit(self, irc, msg, args):
        """[<int return value>]

        Exits the program with the given return value (the default is 0)
        """
        try:
            i = int(args[0])
        except (ValueError, IndexError):
            i = 0
        for driver in drivers._drivers.itervalues():
            driver.die()
        for irc in world.ircs[:]:
            irc.die()
        debug.exit(i)

    def flush(self, irc, msg, args):
        """takes no arguments

        Runs all the periodic flushers in world.flushers.
        """
        world.flush()
        irc.reply(msg, conf.replySuccess)

    def upkeep(self, irc, msg, args):
        """takes no arguments

        Runs the standard upkeep stuff (flushes and gc.collects()).
        """
        collected = world.upkeep()
        if gc.garbage:
            irc.reply(msg, 'Garbage!  %r' % gc.garbage)
        else:
            irc.reply(msg, '%s collected.' % utils.nItems(collected, 'object'))

    def set(self, irc, msg, args):
        """<name> <value>

        Sets the runtime variable <name> to <value>.  Currently used variables
        include "noflush" which, if set to true value, will prevent the
        periodic flushing that normally occurs.
        """
        (name, value) = privmsgs.getArgs(args, optional=1)
        world.tempvars[name] = value
        irc.reply(msg, conf.replySuccess)

    def unset(self, irc, msg, args):
        """<name>

        Unsets the value of variables set via the 'set' command.
        """
        name = privmsgs.getArgs(args)
        try:
            del world.tempvars[name]
            irc.reply(msg, conf.replySuccess)
        except KeyError:
            irc.error(msg, 'That variable wasn\'t set.')

    def load(self, irc, msg, args):
        """<plugin>

        Loads the plugin <plugin> from any of the directories in
        conf.pluginDirs; usually this includes the main installed directory
        and 'plugins' in the current directory.  Be sure not to have ".py" at
        the end.
        """
        name = privmsgs.getArgs(args)
        for cb in irc.callbacks:
            if cb.name() == name:
                irc.error(msg, 'That module is already loaded.')
                return
        try:
            module = loadPluginModule(name)
        except ImportError, e:
            if name in str(e):
                irc.error(msg, 'No plugin %s exists.' % name)
            else:
                irc.error(msg, debug.exnToString(e))
            return
        loadPluginClass(irc, module)
        irc.reply(msg, conf.replySuccess)

    '''
    def superreload(self, irc, msg, args):
        """<module name>

        Reloads a module, hopefully such that all vestiges of the old module
        are gone.
        """
        name = privmsgs.getArgs(args)
        world.superReload(__import__(name))
        irc.reply(msg, conf.replySuccess)
    '''

    def reload(self, irc, msg, args):
        """<plugin>

        Unloads and subsequently reloads the callback by name; use the 'list'
        command to see a list of the currently loaded callbacks.
        """
        name = privmsgs.getArgs(args)
        callbacks = irc.removeCallback(name)
        if callbacks:
            try:
                module = loadPluginModule(name)
                for callback in callbacks:
                    callback.die()
                    del callback
                gc.collect()
                callback = loadPluginClass(irc, module)
                irc.reply(msg, conf.replySuccess)
            except ImportError:
                for callback in callbacks:
                    irc.addCallback(callback)
                irc.error(msg, 'No plugin %s exists.' % name)
        else:
            irc.error(msg, 'There was no callback %s.' % name)

    def unload(self, irc, msg, args):
        """<plugin>

        Unloads the callback by name; use the 'list' command to see a list
        of the currently loaded callbacks.
        """
        name = privmsgs.getArgs(args)
        callbacks = irc.removeCallback(name)
        if callbacks:
            for callback in callbacks:
                callback.die()
                del callback
            gc.collect()
            irc.reply(msg, conf.replySuccess)
        else:
            irc.error(msg, 'There was no callback %s' % name)

    def reconf(self, irc, msg, args):
        """takes no arguments

        Reloads the configuration files in conf.dataDir: conf/users.conf and
        conf/channels.conf, by default.
        """
        ircdb.users.reload()
        ircdb.channels.reload()
        irc.reply(msg, conf.replySuccess)

    def connect(self, irc, msg, args):
        """<server> [<port>]

        Connects a new Irc instance to <server>:<port> (<port> defaults to 6667
        if not given).  The bot will automatically join the channels he
        normally joins.
        """
        (server, port) = privmsgs.getArgs(args, optional=1)
        if not port:
            port = 6667
        else:
            try:
                port = int(port)
            except ValueError:
                irc.error(msg, '<port> must be an integer.')
                return
        cbs = map(irc.getCallback, ['Owner', 'ConfigAfter376'])
        newIrc = irclib.Irc(irc.nick, irc.user, irc.ident,
                            irc.password, callbacks=cbs)
        driver = drivers.newDriver((server, port), newIrc)
        newIrc.driver = driver
        irc.reply(msg, conf.replySuccess)

    def disconnect(self, irc, msg, args):
        """[<server>]

        Disconnects from the server, if given; otherwise disconnects from the
        server on which it received the command.
        """
        server = privmsgs.getArgs(args, needed=0, optional=1)
        if not server:
            server = irc.server[0]
        me = False
        for otherIrc in world.ircs[:]: # Copy because they remove themselves.
            if otherIrc.driver.server[0] == server:
                if otherIrc == irc:
                    me = True
                otherIrc.die()
        if not me:
            irc.reply(msg, conf.replySuccess)
                


Class = Owner


# vim:set shiftwidth=4 tabstop=8 expandtab textwidth=78:

