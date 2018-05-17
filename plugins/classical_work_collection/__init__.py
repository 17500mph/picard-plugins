# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 Mark Evens
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

PLUGIN_NAME = u'Classical Work Collections'
PLUGIN_AUTHOR = u'Mark Evens'
PLUGIN_DESCRIPTION = u"""Adds a context menu 'add works to collections', which operates from track or album selections
regardless of whether a file is present. It presents a dialog box showing available work collections. Select the 
collection(s)and a confirmation dialog appears. Confirming will add works from all the selected tracks to the 
selected collections. 
If the plugin 'Classical Extras' has been used then all parent works will also be added."""
PLUGIN_VERSION = "0.1"
PLUGIN_API_VERSIONS = ["1.3.0", "1.4.0"]
PLUGIN_LICENSE = "GPL-2.0"
PLUGIN_LICENSE_URL = "https://www.gnu.org/licenses/gpl-2.0.html"

import locale
import math
from functools import partial
from picard.album import Album
from picard.track import Track
from picard.ui.itemviews import BaseAction, register_album_action, register_track_action
from picard import config, log
from PyQt4 import QtCore, QtGui
from picard.plugins.classical_work_collection.ui_select_collections import Ui_CollectionsDialog
from picard.plugins.classical_work_collection.ui_confirm import Ui_ConfirmDialog
from picard.plugins.classical_work_collection.workscollection import Collection, user_collections, load_user_collections, WorksXmlWebService

update_list = []
SUBMISSION_LIMIT = 200
PROVIDE_ANALYSIS = True

def add_works_to_list(tracks):
    works = []
    for track in tracks:
        metadata = track.metadata
        if '~cwp_part_levels' in metadata and metadata['~cwp_part_levels'].isdigit():  # Classical Extras plugin
            for ind in range(0, int(metadata['~cwp_part_levels']) + 1):
                if '~cwp_workid_' + str(ind) in metadata:
                    work = eval(metadata['~cwp_workid_' + str(ind)])
                    if isinstance(work, tuple):
                        works += list(work)
                    elif isinstance(work, list):
                        works += work
                    elif isinstance(work, basestring):
                        works.append(work)
        else:
            if 'musicbrainz_workid' in metadata:  # No Classical Extras plugin
                works.append(metadata['musicbrainz_workid'])
    return works


def process_collection(error=None):
    if error:
        return
    if update_list:
        collection, work_list, diff = update_list[0]
        confirm = ConfirmDialog(len(work_list), len(diff), collection.name)
        if PROVIDE_ANALYSIS:
            confirm.get_collection_members(confirm_dialog, confirm, collection, collection.id, collection.size, work_list)
        else:
            confirm_dialog(confirm, collection, None, work_list)
        del update_list[0]


def confirm_dialog(confirm, collection, member_set, work_list):
    if PROVIDE_ANALYSIS:
        diff = set(work_list) - member_set
        if len(diff) > 0:
            confirm.ui.label_2.setText(str(len(diff)) + ' new works, from ' + str(len(set(work_list))) + ' selected, will be added.')
        else:
            confirm.ui.label_2.setText('All ' + str(len(set(work_list))) + ' selected works are already in the collection - no more will be added.')
    else:
        diff = set(work_list)
        confirm.ui.label.setText('Adding ' + str(len(diff)) + ' works to the collection "' + collection.name + '"')
        confirm.ui.label_2.setText('(Some may already be in the collection)')
    confirmation = confirm.exec_()
    if confirmation == 1:
        if diff:
            collection.add_works(diff, process_collection, SUBMISSION_LIMIT)
            return
        else:
            log.debug('%s: nothing new to add', PLUGIN_NAME)
    elif confirmation == 0:
        pass
    else:
        log.error('%s: Error in dialog', PLUGIN_NAME)
    process_collection()  # check if there is anything left to do

class AddWorkCollection(BaseAction):
    NAME = 'Add works to collections'

    def callback(self, objs):
        global SUBMISSION_LIMIT
        global PROVIDE_ANALYSIS
        work_list = []
        selected_albums = [a for a in objs if type(a) == Album]
        for album in selected_albums:
            work_list += add_works_to_list(album.tracks)
        selected_tracks = [t for t in objs if type(t) == Track]
        if selected_tracks:
            work_list += add_works_to_list(selected_tracks)
        dialog = SelectCollectionsDialog()
        # Note: this loads the collection objects, which may result in a slight delay before they appear in the dialog
        result = dialog.exec_()
        if result == 1:  # QDialog.Accepted
            SUBMISSION_LIMIT = dialog.ui.max_works.value()
            PROVIDE_ANALYSIS = dialog.ui.provide_analysis.isChecked()
            # log.error('constants set: SUBMISSION_LIMIT = %s, PROVIDE_ANALYSIS = %s', SUBMISSION_LIMIT, PROVIDE_ANALYSIS)
            if dialog.ui.collection_list.selectedItems():
                for item in dialog.ui.collection_list.selectedItems():
                    id = item.data(32)
                    name = item.data(33)
                    size = item.data(34)
                    collection = Collection(id, name, size)  # user_collections[id]
                    if set(work_list) & collection.pending:
                        return
                    diff = set(work_list) - collection.works
                    update_list.append((collection, work_list, diff))
            else:
                confirm = ConfirmDialog(0, 0, 'None')
                confirm.ui.label.setText('No collections selected')
                confirm.ui.label_2.setText('')
                confirm.exec_()
        elif result == 0:
            pass
        else:
            log.error('%s: Error in dialog', PLUGIN_NAME)
        process_collection()




class SelectCollectionsDialog(QtGui.QDialog):

    def __init__(self, parent=None):
        QtGui.QDialog.__init__(self, parent)
        self.ui = Ui_CollectionsDialog()
        self.ui.setupUi(self)
        self.ui.buttonBox.accepted.connect(self.accept)
        self.ui.buttonBox.rejected.connect(self.reject)
        self.ui.max_works.setValue(200)
        self.ui.provide_analysis.setChecked(True)
        load_user_collections(self.display_collections)

    def display_collections(self):
        collections = self.ui.collection_list  # collection_list is a QListWidget

        for id, collection in sorted(user_collections.iteritems(),
                                     key=lambda k_v:
                                     (locale.strxfrm(k_v[1].name.encode('utf-8')), k_v[0])):

            item = QtGui.QListWidgetItem()
            item.setText(collection.name + ' (' + str(collection.size) + ')')
            item.setData(32, id)  # role #32 is first available user role
            item.setData(33, collection.name)
            item.setData(34, collection.size)
            collections.addItem(item)


class ConfirmDialog(QtGui.QDialog):

    def __init__(self, num_works, num_diff, selected_collection, parent=None):
        QtGui.QDialog.__init__(self, parent)
        self.ui = Ui_ConfirmDialog()
        self.ui.setupUi(self)
        self.ui.buttonBox.accepted.connect(self.accept)
        self.ui.buttonBox.rejected.connect(self.reject)
        self.member_set = set()

    def get_collection_members(self, callback, confirm, collection, id, size, work_list):
        # log.error(' in get_collection_members. work_list =')
        # log.error(work_list)
        works_xmlws = WorksXmlWebService()
        limit = 100
        if isinstance(size, basestring):
            if size.isdigit():
                size = int(size)
            else:
                return
        chunks = int(math.ceil(float(size) / float(limit)))
        for chunk in range(0, chunks):
            # log.error('chunk %s of %s', chunk, chunks)
            offset = chunk * limit
            # log.error('offset = %s', offset)
            if chunk == chunks - 1:
                chunk_size = size - offset
            else:
                chunk_size = limit
            if chunk == 0:  # Lookups appear to be on a LIFO basis (?!*+$!)
                end = True
            else:
                end = False
            # log.error('call get_collection')
            works_xmlws.get_collection(id, partial(self.add_collection_members, callback, confirm, collection, work_list, end, chunk_size), limit, offset)

    def add_collection_members(self, callback, confirm, collection, work_list, end, chunk_size, document, reply, error):
        tagger = QtCore.QObject.tagger
        if error:
            tagger.window.set_statusbar_message(
                N_("Error loading collections: %(error)s"),
                {'error': unicode(reply.errorString())},
                echo=log.error
            )
            return
        node = document.metadata[0].collection
        if node:
            # log.error('self.member_set before = %r', self.member_set)
            self.member_set = self.member_set | self.process_node(node[0], chunk_size)
            # log.error('self.member_set after = %r', self.member_set)
            # log.error('end = %r, len = %s', end, len(self.member_set))
        else:
            return
        if end:
            self.ui.label.setText('Collection "' + collection.name + '" has ' + str(len(self.member_set)) + ' existing members')
            callback(confirm, collection, self.member_set, work_list)

    def process_node(self, node, chunk_size):
        work_set = set()
        if node.attribs.get(u"entity_type") == u"work":
            # name = node.name[0].text
            size = min(int(node.work_list[0].count), chunk_size)
            for work_item in range(0, size):
                work = node.work_list[0].work[work_item]
                work_set.add(work.id)
        return work_set


work_collection = AddWorkCollection()
register_album_action(work_collection)
register_track_action(work_collection)
