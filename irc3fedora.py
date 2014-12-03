# -*- coding: utf-8 -*-
import datetime
import logging
import logging.config

import requests
import pytz

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


class Utils(object):
    """ Some handy utils for datagrepper visualization. """

    @classmethod
    def sparkline(cls, values):
        bar = u'▁▂▃▄▅▆▇█'
        barcount = len(bar) - 1
        values = map(float, values)
        mn, mx = min(values), max(values)
        extent = mx - mn

        if extent == 0:
            indices = [0 for n in values]
        else:
            indices = [int((n - mn) / extent * barcount) for n in values]

        unicode_sparkline = u''.join([bar[i] for i in indices])
        return unicode_sparkline

    @classmethod
    def daterange(cls, start, stop, steps):
        """ A generator for stepping through time. """
        delta = (stop - start) / steps
        current = start
        while current + delta <= stop:
            yield current, current + delta
            current += delta


@irc3.plugin
class FedoraPlugin:
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
        self.fasclient = AccountSystem(
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
        meetings = FedoraPlugin._query_fedocal(calendar=calendar)
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
    def badges(self, mask, target, args):
        """badges <username>

        Return badges statistics about a user.

            %%badges <username>
        """
        name = args['<username>']

        url = "https://badges.fedoraproject.org/user/" + name
        d = requests.get(url + "/json").json()

        if 'error' in d:
            response = d['error']
        else:
            template = "{name} has unlocked {n} Fedora Badges:  {url}"
            n = len(d['assertions'])
            response = template.format(name=name, url=url, n=n)

        self.bot.privmsg(target, '%s: %s' % (mask.nick, response))

    @command
    def branches(self, mask, target, args):
        """branches <package>

        Return the branches a package is in.

            %%branches <package>
        """
        package = args['<package>']

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

            %%fas <pattern>
        """
        users = self.fasclient.people_query(
                constraints={
                    #'username': args['<pattern>'],
                    'ircnick': args['<pattern>'],
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

            %%fasinfo <username>
        """
        name = args['<username>']

        try:
            person = self.fasclient.person_by_username(name)
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
            roles = self.fasclient.people_query(
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
        name = args['<group name>']

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
        name = args['<username>']
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
        name = args['<username>']
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
        name = args['<username>']

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
                name, timezone_name)
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        msg = 'The current local time of "%s" is: "%s" (timezone: %s)' % (
            name, time.strftime('%H:%M'), timezone_name)
        self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def members(self, mask, target, args):
        """members <group short name>

        Return the list of members for the selected group

            %%members <group name>
        """
        name = args['<group name>']

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

            %%nextmeeting <channel>
        """
        channel = args['<channel>']

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
    def nextmeetings(self, mask, target, args):
        """nextmeetings

        Return the next meetings scheduled for any channel(s).

            %%nextmeetings
        """
        msg = 'One moment, please...  Looking up the channel list.'
        self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

        url = 'https://apps.fedoraproject.org/calendar/api/locations/'
        locations = requests.get(url).json()['locations']
        meetings = sorted(chain(*[
            self._future_meetings(location)
            for location in locations
            if 'irc.freenode.net' in location
        ]), key=itemgetter(0))

        test, meetings = tee(meetings)
        try:
            test.next()
        except StopIteration:
            response = "There are no meetings scheduled at all."
            self.bot.privmsg(target, '%s: %s' % (mask.nick, response))
            return

        for date, meeting in islice(meetings, 0, 5):
            response = "In #%s is %s (starting %s)" % (
                meeting['meeting_location'].split('@')[0].strip(),
                meeting['meeting_name'],
                arrow.get(date).humanize(),
            )
            self.bot.privmsg(target, '%s: %s' % (mask.nick, response))

    @command
    def pushduty(self, mask, target, args):
        """pushduty

        Return the list of people who are on releng push duty right now.

            %%pushduty
        """

        def get_persons():
            for meeting in self._meetings_for('release-engineering'):
                yield meeting['meeting_name']

        persons = list(get_persons())

        url = "https://apps.fedoraproject.org/" + \
            "calendar/release-engineering/"

        if not persons:
            response = "Nobody is listed as being on push duty right now..."
            self.bot.privmsg(target, '%s: %s' % (mask.nick, response))
            self.bot.privmsg(target, '%s: - %s' % (mask.nick, url))
            return

        persons = ", ".join(persons)
        response = "The following people are on push duty: %s" % persons
        self.bot.privmsg(target, '%s: %s' % (mask.nick, response))
        self.bot.privmsg(target, '%s: - %s' % (mask.nick, url))

    @command
    def quote(self, mask, target, args):
        """quote <SYMBOL> [daily, weekly, monthly, quarterly]

        Return some datagrepper statistics on fedmsg categories.

            %%quote <symbol> <frame>
        """

        symbol = args['<symbol>']
        frame = 'daily'
        if 'frame' in args:
            frame = args['<frame>']

        # Second, build a lookup table for symbols.  By default, we'll use the
        # fedmsg category names, take their first 3 characters and uppercase
        # them.  That will take things like "wiki" and turn them into "WIK" and
        # "bodhi" and turn them into "BOD".  This handles a lot for us.  We'll
        # then override those that don't make sense manually here.  For
        # instance "fedoratagger" by default would be "FED", but that's no
        # good.  We want "TAG".
        # Why all this trouble?  Well, as new things get added to the fedmsg
        # bus, we don't want to have keep coming back here and modifying this
        # code.  Hopefully this dance will at least partially future-proof us.
        symbols = dict([
            (processor.__name__.lower(), processor.__name__[:3].upper())
            for processor in fedmsg.meta.processors
        ])
        symbols.update({
            'fedoratagger': 'TAG',
            'fedbadges': 'BDG',
            'buildsys': 'KOJ',
            'pkgdb': 'PKG',
            'meetbot': 'MTB',
            'planet': 'PLN',
            'trac': 'TRC',
            'mailman': 'MM3',
        })

        # Now invert the dict so we can lookup the argued symbol.
        # Yes, this is vulnerable to collisions.
        symbols = dict([(sym, name) for name, sym in symbols.items()])

        # These aren't user-facing topics, so drop 'em.
        del symbols['LOG']
        del symbols['UNH']
        del symbols['ANN']  # And this one is unused...

        key_fmt = lambda d: ', '.join(sorted(d.keys()))

        if symbol not in symbols:
            response = "No such symbol %r.  Try one of %s"
            msg = response % (symbol, key_fmt(symbols))
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        # Now, build another lookup of our various timeframes.
        frames = dict(
            daily=datetime.timedelta(days=1),
            weekly=datetime.timedelta(days=7),
            monthly=datetime.timedelta(days=30),
            quarterly=datetime.timedelta(days=91),
        )

        if frame not in frames:
            response = "No such timeframe %r.  Try one of %s"
            msg = response % (frame, key_fmt(frames))
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))
            return

        category = [symbols[symbol]]

        t2 = datetime.datetime.utcnow()
        t1 = t2 - frames[frame]
        t0 = t1 - frames[frame]

        # Count the number of messages between t0 and t1, and between t1 and t2
        query1 = dict(start=t0, end=t1, category=category)
        query2 = dict(start=t1, end=t2, category=category)

        # Do this async for superfast datagrepper queries.
        tpool = ThreadPool()
        batched_values = tpool.map(datagrepper_query, [
            dict(start=x, end=y, category=category)
            for x, y in Utils.daterange(t1, t2, SPARKLINE_RESOLUTION)
        ] + [query1, query2])

        count2 = batched_values.pop()
        count1 = batched_values.pop()

        # Just rename the results.  We'll use the rest for the sparkline.
        sparkline_values = batched_values

        yester_phrases = dict(
            daily="yesterday",
            weekly="the week preceding this one",
            monthly="the month preceding this one",
            quarterly="the 3 months preceding these past three months",
        )
        phrases = dict(
            daily="24 hours",
            weekly="week",
            monthly="month",
            quarterly="3 months",
        )

        if count1 and count2:
            percent = ((float(count2) / count1) - 1) * 100
        elif not count1 and count2:
            # If the older of the two time periods had zero messages, but there
            # are some in the more current period.. well, that's an infinite
            # percent increase.
            percent = float('inf')
        elif not count1 and not count2:
            # If counts are zero for both periods, then the change is 0%.
            percent = 0
        else:
            # Else, if there were some messages in the old time period, but
            # none in the current... then that's a 100% drop off.
            percent = -100

        sign = lambda value: value >= 0 and '+' or '-'

        template = u"{sym}, {name} {sign}{percent:.2f}% over {phrase}"
        response = template.format(
            sym=symbol,
            name=symbols[symbol],
            sign=sign(percent),
            percent=abs(percent),
            phrase=yester_phrases[frame],
        )
        self.bot.privmsg(target, '%s: %s' % (mask.nick, response))

        # Now, make a graph out of it.
        sparkline = Utils.sparkline(sparkline_values)

        template = u"     {sparkline}  ⤆ over {phrase}"
        response = template.format(
            sym=symbol,
            sparkline=sparkline,
            phrase=phrases[frame]
        )
        self.bot.privmsg(target, '%s: %s' % (mask.nick, response))

        to_utc = lambda t: time.gmtime(time.mktime(t.timetuple()))
        # And a final line for "x-axis tics"
        t1_fmt = time.strftime("%H:%M UTC %m/%d", to_utc(t1))
        t2_fmt = time.strftime("%H:%M UTC %m/%d", to_utc(t2))
        padding = u" " * (SPARKLINE_RESOLUTION - len(t1_fmt) - 3)
        template = u"     ↑ {t1}{padding}↑ {t2}"
        response = template.format(t1=t1_fmt, t2=t2_fmt, padding=padding)
        self.bot.privmsg(target, '%s: %s' % (mask.nick, response))

    @command
    def sponsors(self, mask, target, args):
        """sponsors <group short name>

        Return the sponsors list for the selected group

            %%sponsors <group name>
        """
        name = args['<group name>']

        msg = None
        try:
            group = self.fasclient.group_members(name)
            sponsors = ''
            for person in group:
                if person['role_type'] == 'sponsor':
                    sponsors += person['username'] + ' '
                elif person['role_type'] == 'administrator':
                    sponsors += '@' + person['username'] + ' '
            msg = 'Sponsors for %s: %s' % (name, sponsors)
        except AppError:
            msg = 'There is no group %s.' % name

        if msg is not None:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def vacation(self, mask, target, args):
        """vacation

        Return the list of people who are on vacation right now according
        to fedocal.

            %%vacation
        """

        def get_persons():
            for meeting in self._meetings_for('vacation'):
                for manager in meeting['meeting_manager']:
                    yield manager

        persons = list(get_persons())

        if not persons:
            response = "Nobody is listed as being on vacation right now..."
            self.bot.privmsg(target, '%s: %s' % (mask.nick, response))
            url = "https://apps.fedoraproject.org/calendar/vacation/"
            self.bot.privmsg(target, '%s: - %s' % (mask.nick, url))
            return

        persons = ", ".join(persons)
        response = "The following people are on vacation: %s" % persons
        self.bot.privmsg(target, '%s: %s' % (mask.nick, response))
        url = "https://apps.fedoraproject.org/calendar/vacation/"
        self.bot.privmsg(target, '%s: - %s' % (mask.nick, url))

    @command
    def what(self, mask, target, args):
        """what <package>

        Returns a description of a given package.

            %%what <package>
        """
        package = args['<package>']
        msg = None
        try:
            summary = self.bugzacl['Fedora'][package]['summary']
            msg = "%s: %s" % (package, summary)
        except KeyError:
            msg = "No such package exists."

        if msg is not None:
            self.bot.privmsg(target, '%s: %s' % (mask.nick, msg))

    @command
    def whoowns(self, mask, target, args):
        """whoowns <package>

        Return more information about the specified user

            %%whoowns <package>
        """

        package = args['<package>']

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

    @command
    def wikilink(self, mask, target, args):
        """wikilink <username>

        Return MediaWiki link syntax for a FAS user's page on the wiki.

            %%wikilink <username>
        """
        name = args['<username>']

        person = msg = None
        try:
            person = self.fasclient.person_by_username(name)
        except:
            msg = 'Error getting info for user: "%s"' % name
        if not person:
            msg = 'User "%s" doesn\'t exist' % name
        else:
            msg = "[[User:%s|%s]]" % (person["username"],
                                      person["human_name"] or '')

        if msg is not None:
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
