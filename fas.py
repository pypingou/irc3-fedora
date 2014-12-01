# -*- coding: utf-8 -*-
import logging.config
from irc3.compat import asyncio
from irc3.plugins.command import command
import logging
import irc3

from irc3d import IrcServer


from fedora.client import AppError
from fedora.client import AuthError
from fedora.client import ServerError
from fedora.client.fas2 import AccountSystem
from fedora.client.fas2 import FASError
from pkgdb2client import PkgDB


FAS = None
PKGDB = PkgDB()


@irc3.plugin
class FasPlugin:
    """A plugin is a class which take the IrcBot as argument
    """

    requires = [
        'irc3.plugins.core',
        'irc3.plugins.command',
    ]

    def __init__(self, bot):
        self.bot = bot

        fas_url = bot.config['fas']['url']
        fas_username = bot.config['fas']['username']
        fas_password = bot.config['fas']['password']
        self.fas = AccountSystem(
            fas_url, username=fas_username, password=fas_password)

    @command
    def fas(self, mask, target, args):
        """fas <pattern>

        Searches a pattern in the list of FAS user

            %%fas <pattern>...
        """
        users = self.fas.people_query(
                constraints={
                    #'username': args['<pattern>'][0],
                    'ircnick': args['<pattern>'][0],
                },
                columns=['username', 'ircnick', 'email']
            )
        if users:
            msg = ', '.join(
                [
                '%s (%s) <%s>' % (user.username, user.ircnick, user.email)
                for user in users
                ]
            )
        else:
            msg = 'No user matching found'
        self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def fasinfo(self, mask, target, args):
        """fasinfo <pattern>

        Return more information about the specified user

            %%fasinfo <username>...
        """
        name = args['<username>'][0]

        try:
            person = self.fas.person_by_username(name)
        except:
            msg = 'Error getting info for user: "%s"' % name
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        if not person:
            msg = 'User "%s" doesn\'t exist' % name
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        person['creation'] = person['creation'].split(' ')[0]
        string = (
            "User: %(username)s, Name: %(human_name)s"
            ", email: %(email)s, Creation: %(creation)s"
            ", IRC Nick: %(ircnick)s, Timezone: %(timezone)s"
            ", Locale: %(locale)s"
            ", GPG key ID: %(gpg_keyid)s, Status: %(status)s") % person
        self.bot.privmsg(target, '%s: %s' % (mask.nick, string))

        # List of unapproved groups is easy
        unapproved = ''
        for group in person['unapproved_memberships']:
            unapproved = unapproved + "%s " % group['name']
        if unapproved != '':
            msg = 'Unapproved Groups: %s' % unapproved
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

        # List of approved groups requires a separate query to extract roles
        constraints = {
            'username': name, 'group': '%',
            'role_status': 'approved'}
        columns = ['username', 'group', 'role_type']
        roles = []
        try:
            roles = self.fas.people_query(
                constraints=constraints,
                columns=columns)
        except:
            msg = 'Error getting group memberships.'
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        approved = ''
        for role in roles:
            if role['role_type'] == 'sponsor':
                approved += '+' + role['group'] + ' '
            elif role['role_type'] == 'administrator':
                approved += '@' + role['group'] + ' '
            else:
                approved += role['group'] + ' '
        if approved == '':
            approved = "None"
        msg = 'Approved Groups: %s' % approved
        self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))


def main():
    # logging configuration
    logging.config.dictConfig(irc3.config.LOGGING)

    loop = asyncio.get_event_loop()

    server = IrcServer.from_argv(loop=loop)
    bot = irc3.IrcBot.from_argv(loop=loop).run()

    loop.run_forever()


if __name__ == '__main__':
    main()
