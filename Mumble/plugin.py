###
# Copyright (c) 2013, Alexander Minges
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

import Ice
import threading, time
import datetime
import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
try:
  from supybot.i18n import PluginInternationalization, internationalizeDocstring
  _ = PluginInternationalization('Mumble')
except :
  _ = lambda x : x
  internationalizeDocstring = lambda x : x

Ice.loadSlice('', ['-I' + Ice.getSliceDir(), self.registryValue('mumbleSlice') ] )
import Murmur

class metaCallbackI(Murmur.MetaCallback):
    def started(self, s, current=None):
        serverR=Murmur.ServerCallbackPrx.uncheckedCast(adapter.addWithUUID(serverCallbackI(server, current.adapter)))
        s.addCallback(serverR)

class serverCallbackI(Murmur.ServerCallback):
    def __init__(self, server, adapter, m):
        self.server = server
        self.m = m
    def userConnected(self, p, current=None):
        self.m.SayChannels(self.m.irc, "%s connected"%p.name)
    def userDisconnected(self, p, current=None):
        self.m.SayChannels(self.m.irc, "%s left"%p.name)
    def userTextMessage(self, p, message, current=None):
        self.m.SayChannels(self.m.irc, "<%s> %s"%(p.name, message.text))
        
 
@internationalizeDocstring
class Mumble(callbacks.Plugin):
    """The Mumble plugin monitors the status of a Mumble server (murmur)
       and provides commands to send messages directly to channels/users on
       the Mumble server."""
    threaded = True
    
    def __init__(self, irc):
        self.__parent = super(Mumble, self)
        self.__parent.__init__(irc)

        self.irc = irc
        
       
        prop = Ice.createProperties([])
        prop.setProperty("Ice.ImplicitContext", "Shared")
        prop.setProperty("Ice.MessageSizeMax",  "65535")
        
        idd = Ice.InitializationData()
        idd.properties = prop
        
        self.ice = Ice.initialize(idd)
        self.ice.getImplicitContext().put("secret", 
                                           self.registryValue('mumbleSecret'))
        
        connstr = "Meta:tcp -h {} -p {}".format(self.registryValue('serverIp'), 
                                                self.registryValue('serverPort'))
        proxy = self.ice.stringToProxy(connstr)
        
        self.meta = Murmur.MetaPrx.checkedCast(proxy)
        self.server = self.meta.getServer(1)

        adapter = self.ice.createObjectAdapterWithEndpoints("Callback.Client", "tcp -h {}".format(self.registryValue('serverIp')))

        self.metaR=Murmur.MetaCallbackPrx.uncheckedCast(adapter.addWithUUID(metaCallbackI()))

        adapter.activate()

        self.meta.addCallback(self.metaR)
        for server in self.meta.getBootedServers():
            serverR=Murmur.ServerCallbackPrx.uncheckedCast(adapter.addWithUUID(serverCallbackI(server, adapter, self)))
            server.addCallback(serverR)


        self.announceChannels = self.GetIrcChannels(irc)

    def die(self):
        self.meta.removeCallback(self.metaR)
        self.ice.shutdown()
        self.__parent.die()
    
    def GetUsers(self):
        users = self.server.getUsers()
        return users

    def GetIrcChannels(self, irc):
        # if announceChannels is set, only send to these channels
        if self.registryValue('announceChannels'):
            channels = self.registryValue('announceChannels')
        # else send to all channels the bot is connected
        else:
            channels = irc.state.channels
        
        #return irc.state.channels 
        return channels

    def SayChannels(self, irc, text, channels=None):
        if not channels:
            channels = self.announceChannels
        for channel in channels:
            irc.queueMsg(ircmsgs.privmsg(channel, "[mumble] %s"%text))

    def GetMumbleChannels(self):
        """Obtain a list of channels"""
        tmp = self.server.getChannels()

        channels = {}
        for key in tmp:
            c = tmp[key]
            channels[str(c.id)] = {"id" : str(c.id),
                                    "name" : str(c.name),
                                    "parent" : str(c.parent),
                                    "description": str(c.description),
                                    "temporary" : bool(c.temporary),
                                    "links" : c.links,
                                    "position" : int(c.position)}
        return channels
     
    def mumblestatus(self, irc, msg, args):
        """takes no arguments
        
        Returns a status message of the mumble server
        """
        uptime = str(datetime.timedelta(seconds=self.server.getUptime()))
        running = self.server.isRunning()
        
        msg_str = _('The server is ')
        
        if running:
            msg_str += _('online and ')
        else:
            msg_str += _('offline and has been ')
            
        msg_str += _('running for {}').format(uptime)
        
        irc.reply(msg_str)
    mumblestatus = wrap(mumblestatus)

    @internationalizeDocstring      
    def mumbleusers(self, irc, msg, args):
        """takes no arguments

        Returns a list of connected mumble users
        """
        users = self.GetUsers()
        usernames = []  
        for uk in users:
            usernames.append(users[uk].name)

        name_str = ",".join(usernames)
        if len(usernames) > 0:
            msg_str = _('Users in mumble: {}').format(",".join(usernames))
        else:
            msg_str = _('No users in mumble')
        irc.reply(msg_str)
    mumbleusers = wrap(mumbleusers)

    @internationalizeDocstring
    def mumblesend(self, irc, msg, args, opts, text):
        """[--dest <value>][--tree <True/False>] <message>

        Sends a message <message> to a channel or user <dest> on the mumble 
        server. <dest> is optional and defaults to the root channel. 
        The optional argument <tree> defines if the message is sent to 
        subchannels of <dest> (only applies if <dest> is 
        a channel and not a user). Default of <tree> is 'True'.
        """
        
        text = _('Message from {} in {}: {}').format(msg.nick, msg.args[0], text)
        
        opts = dict(opts)
        sent = False

        if 'tree' in opts:
            tree = opts['tree']
        else:
            tree = True

        if 'dest' not in opts:
            self.server.sendMessageChannel(0, tree, text)
            msg_txt = _('Message sent to root channel')
            sent = True    
        else:
            channels = self.GetMumbleChannels()
            for id, channel in channels.items():
                if (opts['dest'] == channel['id'] or 
                    opts['dest'].lower() == channel['name'].lower()) :
                    self.server.sendMessageChannel(int(channel['id']), 
                                                   tree, text)
                    msg_txt = _("Message sent to mumble channel '{}'").format(channel['name'])
                    if tree:
                        msg_txt += _(' and subchannels')
                    sent = True
                    break
            if not sent:
                users = self.GetUsers()
                
                for key in users:
                    name = users[key].name
                    session = users[key].session
                    
                    if opts['dest'].lower() == name.lower():
                        self.server.sendMessage(session, text)
                        msg_txt = _("Message sent to mumble user '{}'").format(name)
                        sent = True
                        break
                
        if not sent:
            msg_txt = _("Unknown mumble channel or user '{}'").format(opts['dest'])
                
        irc.reply(msg_txt)
        
    mumblesend = wrap(mumblesend, [getopts({'dest':'text', 
                                            'tree':'boolean'}), 'text'])

Class = Mumble


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
