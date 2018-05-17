# -*- coding: utf-8 -*-
#
# Picard, the next-generation MusicBrainz tagger
# Copyright (C) 2013 Michael Wiencek
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-

# This module is a modified version of collection.py, designed to operate with works rather than releases
# and specifically as part of the classical_work_collection plugin
# It is part of a companion plugin for the Classical Extras plugin
# Modifications are Copyright (C) 2018 Mark Evens

from functools import partial
from PyQt4 import QtCore
from picard import config, log
from picard.webservice import XmlWebService

user_collections = {}

class WorksXmlWebService(XmlWebService):

    def __init__(self, submission_limit=200, parent=None):
        XmlWebService.__init__(self, parent)
        self.sub_limit = submission_limit

    def collection_request(self, id, members):
        while members:
            ids = ";".join(members if len(members) <= self.sub_limit else members[:self.sub_limit])
            members = members[self.sub_limit:]
            yield "/ws/2/collection/%s/works/%s" % (id, ids)

    def get_collection(self, id, handler, limit=100, offset=0):
        host, port = config.setting['server_host'], config.setting['server_port']
        path = "/ws/2/collection"
        queryargs = None
        if id is not None:
            path += "/%s/works" % (id)
            queryargs = {}
            queryargs["limit"] = limit
            queryargs["offset"] = offset
        return self.get(host, port, path, handler, priority=True, important=True,
                        mblogin=True, queryargs=queryargs)


class Collection(QtCore.QObject):

    def __init__(self, id, name, size):
        self.id = id
        self.name = name
        self.pending = set()
        self.size = int(size)
        self.works = set()

    def __repr__(self):
        return '<Collection %s (%s)>' % (self.name, self.id)

    def add_works(self, members, callback, submission_limit):
        works_xmlws = WorksXmlWebService(submission_limit)
        members = members - self.pending
        if members:
            self.pending.update(members)
            host, port = config.setting['server_host'], config.setting['server_port']
            for path in works_xmlws.collection_request(self.id, list(members)):
                works_xmlws.put(host, port, path, "", partial(self._add_finished, members, callback),
                         queryargs=works_xmlws._get_client_queryarg())

    def remove_works(self, members, callback):
        works_xmlws = WorksXmlWebService()
        members = members - self.pending
        if members:
            self.pending.update(members)
            works_xmlws.tagger.works_xmlws.delete_from_collection(self.id, list(members),
                partial(self._remove_finished, members, callback))

    def _add_finished(self, ids, callback, document, reply, error):
        tagger = QtCore.QObject.tagger
        self.pending.difference_update(ids)
        if not error:
            count = len(ids)
            self.works.update(ids)
            self.size += count
            mparms = {
                'count': count,
                'name': self.name
            }
            log.debug('Added %(count)i works to collection "%(name)s"' % mparms)
            self.tagger.window.set_statusbar_message(
                ungettext('Added %(count)i work to collection "%(name)s"',
                          'Added %(count)i works to collection "%(name)s"',
                          count),
                mparms,
                translate=None,
                echo=None
            )
            if callback:
                callback()
        else:
            log.error('Error in collection update. May be that submission is too large.')
            tagger.window.set_statusbar_message(
                N_("Error in collection update: May be that submission is too large.")
            )
            if callback:
                callback(error)

    def _remove_finished(self, ids, callback, document, reply, error):
        self.pending.difference_update(ids)
        if not error:
            count = len(ids)
            self.works.difference_update(ids)
            self.size -= count
            if callback:
                callback()
            mparms = {
                'count': count,
                'name': self.name
            }
            log.debug('Removed %(count)i works from collection "%(name)s"' %
                      mparms)
            self.tagger.window.set_statusbar_message(
                ungettext('Removed %(count)i work from collection "%(name)s"',
                          'Removed %(count)i works from collection "%(name)s"',
                          count),
                mparms,
                translate=None,
                echo=None
            )


def load_user_collections(callback=None):
    tagger = QtCore.QObject.tagger

    def request_finished(document, reply, error):
        if error:
            tagger.window.set_statusbar_message(
                N_("Error loading collections: %(error)s"),
                {'error': unicode(reply.errorString())},
                echo=log.error
            )
            return
        collection_list = document.metadata[0].collection_list[0]
        if "collection" in collection_list.children:
            new_collections = process_node(collection_list)
            for id in set(user_collections.iterkeys()) - new_collections:
                del user_collections[id]
        if callback:
            callback()

    if tagger.xmlws.oauth_manager.is_authorized():
        tagger.xmlws.get_collection_list(partial(request_finished))
    else:
        user_collections.clear()


def process_node(collection_list):
    new_collections = set()
    for node in collection_list.collection:
        if node.attribs.get(u"entity_type") != u"work":
            continue
        new_collections.add(node.id)
        collection = user_collections.get(node.id)
        if collection is None:
            user_collections[node.id] = Collection(node.id, node.name[0].text, node.work_list[0].count)
        else:
            collection.name = node.name[0].text
            collection.size = int(node.work_list[0].count)
    return new_collections
