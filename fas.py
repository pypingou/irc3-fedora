# -*- coding: utf-8 -*-
import logging
import logging.config

import requests

import irc3
from irc3d import IrcServer
from irc3.compat import asyncio
from irc3.plugins.command import command

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

        #self.log.info("Downloading package owners cache")
        data = requests.get(
            'https://admin.fedoraproject.org/pkgdb/api/bugzilla?format=json',
            verify=True).json()
        self.bugzacl = data['bugzillaAcls']

    @staticmethod
    def _future_meetings(location):
        if not location.endswith('@irc.freenode.net'):
            location = '%s@irc.freenode.net' % location
        meetings = Fedora._query_fedocal(location=location)
        now = datetime.datetime.utcnow()

        for meeting in meetings:
            string = "%s %s" % (meeting['meeting_date'],
                                meeting['meeting_time_start'])
            dt = datetime.datetime.strptime(string, "%Y-%m-%d %H:%M:%S")

            if now < dt:
                yield dt, meeting

    @staticmethod
    def _meetings_for(calendar):
        meetings = Fedora._query_fedocal(calendar=calendar)
        now = datetime.datetime.utcnow()

        for meeting in meetings:
            string = "%s %s" % (meeting['meeting_date'],
                                meeting['meeting_time_start'])
            start = datetime.datetime.strptime(string, "%Y-%m-%d %H:%M:%S")
            string = "%s %s" % (meeting['meeting_date_end'],
                                meeting['meeting_time_stop'])
            end = datetime.datetime.strptime(string, "%Y-%m-%d %H:%M:%S")

            if now >= start and now <= end:
                yield meeting

    @staticmethod
    def _query_fedocal(**kwargs):
        url = 'https://apps.fedoraproject.org/calendar/api/meetings'
        return requests.get(url, params=kwargs).json()['meetings']

    @command
    def admins(self, mask, target, args):
        """admins <group short name>

        Return the administrators list for the selected group

            %%admins <group name>...
        """
        name = args['<group name>'][0]

        msg = None
        try:
            group = self.fasclient.group_members(name)
            sponsors = ''
            for person in group:
                if person['role_type'] == 'administrator':
                    sponsors += person['username'] + ' '
            msg = 'Administrators for %s: %s' % (name, sponsors)
        except AppError:
            msg = 'There is no group %s.' % name

        if msg is not None:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def branches(self, mask, target, args):
        """branches <package>

        Return the branches a package is in.

            %%branches <package>...
        """
        package = args['<package>'][0]

        try:
            pkginfo = self.pkgdb.get_package(package)
        except AppError:
            msg = "No such package exists."
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        branch_list = []
        for listing in pkginfo['packages']:
            branch_list.append(listing['collection']['branchname'])
        branch_list.sort()
        msg = ' '.join(branch_list)
        self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

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

    @command
    def group(self, mask, target, args):
        """group <group short name>

        Return information about a Fedora Account System group.

            %%group <group name>
        """
        name = args['<group name>'][0]

        msg = None
        try:
            group = self.fasclient.group_by_name(name)
            msg = '%s: %s' % (name, group['display_name'])
        except AppError:
            msg = 'There is no group "%s".' % name

        if msg is not None:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def hellomynameis(self, mask, target, args):
        """hellomynameis <username>

        Return brief information about a Fedora Account System username. Useful
        for things like meeting roll call and calling attention to yourself.

            %%hellomynameis <username>
        """
        name = args['<username>'][0]
        msg = None
        try:
            person = self.fasclient.person_by_username(name)
        except:
            msg = 'Something blew up, please try again'
        if not person:
            msg = 'Sorry, but you don\'t exist'
        else:
            msg = '%(username)s \'%(human_name)s\' <%(email)s>' % person

        if msg is not None:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def himynameis(self, mask, target, args):
        """himynameis <username>

        Return information about a Fedora Account System group.

            %%himynameis <username>
        """
        name = args['<username>'][0]
        msg = None
        try:
            person = self.fasclient.person_by_username(name)
        except:
            msg = 'Something blew up, please try again'
        if not person:
            msg = 'Sorry, but you don\'t exist'
        else:
            msg = '%(username)s \'Slim Shady\' <%(email)s>' % person

        if msg is not None:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def localtime(self, mask, target, args):
        """localtime <username>

        Returns the current time of the user.
        The timezone is queried from FAS.

            %%localtime <username>
        """
        name = args['<username>'][0]

        try:
            person = self.fasclient.person_by_username(name)
        except:
            msg = 'Error getting info user user: "%s"' % name
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        if not person:
            msg = 'User "%s" doesn\'t exist' % name
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        timezone_name = person['timezone']
        if timezone_name is None:
            msg = 'User "%s" doesn\'t share his timezone' % name
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return
        try:
            time = datetime.datetime.now(pytz.timezone(timezone_name))
        except:
            msg = 'The timezone of "%s" was unknown: "%s"' % (
                name, timezone)
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        msg = 'The current local time of "%s" is: "%s" (timezone: %s)' % (
            name, time.strftime('%H:%M'), timezone_name)
        self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def members(self, mask, target, args):
        """sponsors <group short name>

        Return the list of members for the selected group

            %%members <group name>...
        """
        name = args['<group name>'][0]

        msg = None
        try:
            group = self.fasclient.group_members(name)
            members = ''
            for person in group:
                if person['role_type'] == 'administrator':
                    members += '@' + person['username'] + ' '
                elif person['role_type'] == 'sponsor':
                    members += '+' + person['username'] + ' '
                else:
                    members += person['username'] + ' '
            msg = 'Members of %s: %s' % (name, members)
        except AppError:
            msg = 'There is no group %s.' % name

        if msg is not None:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def nextmeeting(self, mask, target, args):
        """nextmeeting <channel>

        Return the next meeting scheduled for a particular channel.

            %%nextmeeting <channel>...
        """
        channel = args['<channel>'][0]

        channel = channel.strip('#').split('@')[0]
        meetings = sorted(self._future_meetings(channel), key=itemgetter(0))

        test, meetings = tee(meetings)
        try:
            test.next()
        except StopIteration:
            response = "There are no meetings scheduled for #%s." % channel
            self.bot.privmsg(target, '%s: %s' % (mask.nick, response))
            return

        for date, meeting in islice(meetings, 0, 3):
            response = "In #%s is %s (starting %s)" % (
                channel,
                meeting['meeting_name'],
                arrow.get(date).humanize(),
            )
            self.bot.privmsg(target, '%s: %s' % (mask.nick, response))
        base = "https://apps.fedoraproject.org/calendar/location/"
        url = base + urllib.quote("%s@irc.freenode.net/" % channel)
        self.bot.privmsg(target, '%s: - %s' % (mask.nick, url))

    @command
    def whoowns(self, mask, target, args):
        """whoowns <package>

        Return more information about the specified user

            %%whoowns <package>...
        """

        package = args['<package>'][0]

        try:
            mainowner = self.bugzacl['Fedora'][package]['owner']
        except KeyError:
            msg = "No such package exists."
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        others = []
        for key in self.bugzacl:
            if key == 'Fedora':
                continue
            try:
                owner = self.bugzacl[key][package]['owner']
                if owner == mainowner:
                    continue
            except KeyError:
                continue
            others.append("%s in %s" % (owner, key))

        if others == []:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, mainowner))
        else:
            msg = "%s (%s)" % (mainowner, ', '.join(others))
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
