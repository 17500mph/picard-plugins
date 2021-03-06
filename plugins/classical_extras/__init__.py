# -*- coding: utf-8 -*-

PLUGIN_NAME = u'Classical Extras'
PLUGIN_AUTHOR = u'Mark Evens'
PLUGIN_DESCRIPTION = u"""Classical Extras provides tagging enhancements for artists/performers and,
in particular, utilises MB’s hierarchy of works to provide work/movement tags.
All options are set through a user interface in Picard options->plugins.
While it is designed to cater for the complexities of classical music tagging,
it may also be useful for other music which has more than just basic song/artist/album data.
<br /><br />
The options screen provides four tabs for users to control the tags produced:
<br /><br />
1. Artists: Options as to whether artist tags will contain standard MB names, aliases or as-credited names.
Ability to include and annotate names for specialist roles (chorus master, arranger, lyricist etc.).
Ability to read lyrics tags on the file which has been loaded and assign them to track and album levels if required.
(Note: Picard will not normally process incoming file tags).
<br /><br />
2. Tag mapping: in some ways, this is a simple substitute for some of Picard's scripting capability. The main advantage
 is that the plugin will remember what tag mapping you use for each release (or even track).
<br /><br />
3. Works and parts: The plugin will build a hierarchy of works and parts (e.g. Work -> Part -> Movement or
Opera -> Act -> Number) based on the works in MusicBrainz's database. These can then be displayed in tags in a variety
of ways according to user preferences. Furthermore partial recordings, medleys, arrangements and collections of works
are all handled according to user choices. There is a processing overhead for this at present because MusicBrainz limits
look-ups to one per second.
<br /><br />
4. Advanced: Various options to control the detailed processing of the above.
<br /><br />
All user options can be saved on a per-album (or even per-track) basis so that tweaks can be used to deal with
inconsistencies in the MusicBrainz data (e.g. include English titles from the track listing where the MusicBrainz works
are in the composer's language and/or script).
Also existing file tags can be processed (not possible in native Picard) or cleared without affecting cover art.
<br /><br />
See the readme file <a href="https://github.com/metabrainz/picard-plugins/tree/1.0/plugins/classical_extras">
on GitHub here</a> for full details.
"""

########################
# DEVELOPERS NOTES: ####
########################
#  This plugin contains 3 classes:
#
# I. ("EXTRA ARTISTS") Create sorted fields for all performers. Creates a number of variables with alternative values
# for "artists" and "artist".
# Creates an ensemble variable for all ensemble-type performers.
# Also creates matching sort fields for artist and artists.
# Additionally create tags for artist types which are not normally created in Picard - particularly for classical music
#  (notably instrument arrangers).
#
# II. ("PART LEVELS" [aka Work Parts]) Create tags for the hierarchy of works which contain a given track recording
# - particularly for classical music'
# Variables provided for each work level, with implied part names
# Mixed metadata provided including work and title elements
#
# III. ("OPTIONS") Allows the user to set various options including what tags will be written
# (otherwise the classes above will just write outputs to "hidden variables")
#
# The main control routine is at the end of the module

PLUGIN_VERSION = '0.9.3'
PLUGIN_API_VERSIONS = ["1.4.0", "1.4.2"]
PLUGIN_LICENSE = "GPL-2.0"
PLUGIN_LICENSE_URL = "https://www.gnu.org/licenses/gpl-2.0.html"

from picard.ui.options import register_options_page, OptionsPage
from picard.plugins.classical_extras.ui_options_classical_extras import Ui_ClassicalExtrasOptionsPage
from picard import config, log
from picard.config import ConfigSection, BoolOption, IntOption, TextOption
from picard.util import LockableObject, uniqify

# note that in 2.0 picard.webservice will change to picard.util.xml
from picard.webservice import XmlNode
from picard.metadata import register_track_metadata_processor, Metadata
from functools import partial
from datetime import datetime
import collections
import re
import unicodedata
import time
import json
import copy
import os
import itertools
import codecs  # needed for Python 2.7
from PyQt4.QtCore import QXmlStreamReader
from picard.file import File
from picard.track import Track
from picard.tagger import Tagger
from picard.const import USER_DIR
import suffixtree
import operator


##########################
# MODULE-WIDE COMPONENTS #
##########################

# LOGGING

# If logging occurs before any album is loaded, the startup log file will be written
log_files = collections.defaultdict(dict)
# entries are release-ids: to keep track of which log files are open
release_status = collections.defaultdict(dict)
# release_status[release_id]['works'] = True indicates that we are still processing works for release_id
# & similarly for 'artists'
# release_status[release_id]['start'] holds start time of release processing
# release_status[release_id]['name'] holds the album name
# release_status[release_id]['lookups'] holds number of lookups for this release
# release_status[release_id]['file_objects'] holds a cumulative list of file objects (tagger seems a bit unreliable)
# release_status[release_id]['file_found'] = False indicates that "No file with matching trackid" has (yet) been found

def write_log(release_id, log_type, message, *args):
    """
    Custom logging function - if log_info is set, all messages will be written to a custom file in a 'Classical_Extras'
    subdirectory in the same directory as the main Picard log. A different file is used for each album,
    to aid in debugging - the log file is release_id.log. Any startup messages (i.e. before a release has been loaded)
    are written to startup.log
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param log_type: 'error', 'warning', 'debug' or 'info'
    :param message: string, e.g. 'error message for workid: %s'
    :param args: arguments for parameters in string, e.g. if workId then str(workId) will replace %s in the above
    :return:
    """
    options = config.setting
    if not (isinstance(message, str) or isinstance(message, unicode)):
        msg = repr(message)
    else:
        msg = message
    if args:
        msg = msg % args

    if options["log_info"] or log_type == "basic":
        # if log_info is True, all log messages will be written to the custom log, regardless of other log_... settings
        # basic session log will always be written (summary of releases and processing times)
        filename = release_id + ".log"
        log_dir = os.path.join(USER_DIR, "Classical_Extras")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        if release_id not in log_files:
            try:
                if release_id == 'session':
                    log_file = codecs.open(os.path.join(log_dir, filename), 'w', encoding='utf8', buffering=0)
                    # buffering=0 so that session log (low volume) is up to date even if not closed
                else:
                    log_file = codecs.open(os.path.join(log_dir, filename), 'w', encoding='utf8')
                    # default buffering for speed
                # need codecs for python 2.7 to write unicode
                log_files[release_id] = log_file
                log_file.write(PLUGIN_NAME + ' Version:' + PLUGIN_VERSION + '\n')
                if release_id == 'session':
                    log_file.write('session' + '\n')
                else:
                    log_file.write('Release id: ' + release_id + '\n')
                    if release_id in release_status and 'name' in release_status[release_id]:
                        log_file.write('Album name: ' + release_status[release_id]['name'] + '\n')
            except IOError:
                log.error('Unable to open file %s for writing log', filename)
                return
        else:
            log_file = log_files[release_id]
        try:
            log_file.write(log_type[0].upper() + ': ')
            log_file.write(str(datetime.now()) + ' : ')
            log_file.write(msg)
            log_file.write("\n")
        except IOError:
            log.error('Unable to write to log file %s', filename)
            return
    # Only debug, warning and error messages will be written to the main Picard log, if those options have been set
    if log_type != 'info' and log_type != 'basic':  # i.e. non-custom log items
        message2 = PLUGIN_NAME + ': ' + message
    else:
        message2 = message
    if log_type == 'debug' and options["log_debug"]:
        if release_id in release_status and 'debug' in release_status[release_id]:
            add_list_uniquely(release_status[release_id]['debug'], msg)
        else:
            release_status[release_id]['debug'] = [msg]
        if args:
            log.debug(message2, *args)
        else:
            log.debug(message2)
    if log_type == 'warning' and options["log_warning"]:
        if release_id in release_status and 'warnings' in release_status[release_id]:
            add_list_uniquely(release_status[release_id]['warnings'], msg)
        else:
            release_status[release_id]['warnings'] = [msg]
        if args:
            log.warning(message2, *args)
        else:
            log.warning(message2)
    if log_type == 'error' and options["log_error"]:
        if release_id in release_status and 'errors' in release_status[release_id]:
            add_list_uniquely(release_status[release_id]['errors'], msg)
        else:
            release_status[release_id]['errors'] = [msg]
        if args:
            log.error(message2, *args)
        else:
            log.error(message2)


def close_log(release_id, caller):
    # close the custom log file if we are done
    if release_id == 'session':   # shouldn't happen but, just in case, don't close the session log
        return
    if caller in ['works', 'artists']:
        release_status[release_id][caller] = False
    if (caller == 'works' and release_status[release_id]['artists']) or \
            (caller == 'artists' and release_status[release_id]['works']):
        log.error('exiting close_log. only %s done', caller)
        return
    duration = 'N/A'
    lookups = 'N/A'
    if release_id in release_status:
        duration = datetime.now() - release_status[release_id]['start']
        lookups = release_status[release_id]['lookups']
        del release_status[release_id]['start']
        del release_status[release_id]['lookups']
    if release_id in log_files:
        write_log(release_id, 'info', 'Duration = %s. Number of lookups = %s.', duration, lookups)
        write_log(release_id, 'info', 'Closing log file for %s', release_id)
        log_files[release_id].close()
        del log_files[release_id]
    if 'session' in log_files and release_id in release_status:
        write_log('session', 'basic', '\n Completed processing release id %s. Details below:-', release_id)
        if 'name' in release_status[release_id]:
            write_log('session', 'basic', 'Album name %s', release_status[release_id]['name'])
        if 'errors' in release_status[release_id]:
            write_log('session', 'basic', '-------------------- Errors --------------------')
            for error in release_status[release_id]['errors']:
                write_log('session', 'basic', error)
            del release_status[release_id]['errors']
        if 'warnings' in release_status[release_id]:
            write_log('session', 'basic', '-------------------- Warnings --------------------')
            for warning in release_status[release_id]['warnings']:
                write_log('session', 'basic', warning)
            del release_status[release_id]['warnings']
        if 'debug' in release_status[release_id]:
            write_log('session', 'basic', '-------------------- Debug log --------------------')
            for debug in release_status[release_id]['debug']:
                write_log('session', 'basic', debug)
            del release_status[release_id]['debug']
        write_log('session', 'basic', 'Duration = %s. Number of lookups = %s.', duration, lookups)
    if release_id in release_status:
        del release_status[release_id]


# CONSTANTS
_node_name_re = re.compile('[^a-zA-Z0-9]')

def _node_name(n):
    return _node_name_re.sub('_', unicode(n))

def _read_xml(stream):
    document = XmlNode()
    current_node = document
    path = []

    while not stream.atEnd():
        stream.readNext()

        if stream.isStartElement():
            node = XmlNode()
            attrs = stream.attributes()

            for i in xrange(attrs.count()):
                attr = attrs.at(i)
                node.attribs[_node_name(attr.name())] = unicode(attr.value())

            current_node.append_child(_node_name(stream.name()), node)
            path.append(current_node)
            current_node = node

        elif stream.isEndElement():
            current_node = path.pop()

        elif stream.isCharacters():
            current_node.text += unicode(stream.text())

    return document


def parse_data(release_id, obj, response_list, *match):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param obj: an XmlNode object, list or dictionary containing nodes
    :param response_list: working memory for recursive calls
    :param match: list of items to search for in node (see detailed notes below
    :return: a list of matching items (always a list, even if only one item)
    This function takes any XmlNode object, or list thereof,
    and extracts a list of all objects exactly matching the hierarchy listed in match
    match should contain list of each node in hierarchical sequence, with no gaps in the sequence
     of nodes, to lowest level required.
    Insert attribs.attribname:attribvalue in the list to select only branches where attribname
     is attribvalue.
    Insert childname.text:childtext in the list to select only branches where
     a sibling with childname has text childtext.
      (Note: childname can be a dot-list if the text is more than one level down - e.g. child1.child2)
      # TODO - Check this works fully
    """
    DEBUG = False  # config.setting["log_debug"]
    INFO = False  # config.setting["log_info"]
    # Over-ridden options as these can be VERY wordy

    # XmlNode instances are not iterable, so need to convert to dict
    if isinstance(obj, XmlNode):
        obj = obj.__dict__
    if DEBUG or INFO:
        write_log(release_id, 'debug', 'Parsing data - looking for %s', match)
    if INFO:
        write_log(release_id, 'info', 'looking in %s', obj)
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, XmlNode):
                item = item.__dict__
            parse_data(release_id, item, response_list, *match)
        return response_list
    elif isinstance(obj, dict):
        if match[0] in obj:
            if len(match) == 1:
                response = obj[match[0]]
                response_list.append(response)
            else:
                match_list = list(match)
                match_list.pop(0)
                parse_data(release_id, obj[match[0]], response_list, *match_list)
            if INFO:
                write_log(release_id, 'info', 'response_list: %s', response_list)
            return response_list
        elif '.' in match[0]:
            test = match[0].split(':')
            match2 = test[0].split('.')
            test_data = parse_data(release_id, obj, [], *match2)
            if len(test) > 1:
                if test[1] in test_data:
                    if len(match) == 1:
                        response = obj
                        response_list.append(response)
                    else:
                        match_list = list(match)
                        match_list.pop(0)
                        parse_data(release_id, obj, response_list, *match_list)
            else:
                parse_data(release_id, obj, response_list, *match2)
            if INFO:
                write_log(release_id, 'info', 'response_list: %s', response_list)
            return response_list
        else:
            if 'children' in obj:
                parse_data(release_id, obj['children'], response_list, *match)
            if INFO:
                write_log(release_id, 'info', 'response_list: %s', response_list)
            return response_list
    else:
        if INFO:
            write_log(release_id, 'info', 'response_list: %s', response_list)
        return response_list

def create_dict_from_ref_list(options, release_id, ref_list, keys, tags):
    ref_dict_list = []
    for refs in ref_list:
        for ref in refs:
            parsed_refs = [parse_data(release_id, ref, [], t, 'text') for t in tags]
            ref_dict_list.append(dict(zip(keys, parsed_refs)))
    return ref_dict_list


def get_references_from_file(release_id, path, filename):
    """
    Lookup Muso Reference.xml or similar
    :param release_id: name of log file
    :param path: Reference file path
    :param filename: Reference file name
    :return:
    """
    options = config.setting
    composer_dict_list = []
    period_dict_list = []
    genre_dict_list = []
    try:
        xml_file = open(os.path.join(path, filename))
        reply = xml_file.read()
        xml_file.close()
        document = _read_xml(QXmlStreamReader(reply))
        # Composers
        composer_list = parse_data(release_id, document, [], 'ReferenceDB', 'Composer')
        keys = ['name', 'sort', 'birth', 'death', 'country', 'core']
        tags = ['Name', 'Sort', 'Birth', 'Death', 'CountryCode', 'Core']
        composer_dict_list = create_dict_from_ref_list(options, release_id, composer_list, keys, tags)
        # Periods
        period_list = parse_data(release_id, document, [], 'ReferenceDB', 'ClassicalPeriod')
        keys = ['name', 'start', 'end']
        tags = ['Name', 'Start_x0020_Date', 'End_x0020_Date']
        period_dict_list = create_dict_from_ref_list(options, release_id, period_list, keys, tags)
        # Genres
        genre_list = parse_data(release_id, document, [], 'ReferenceDB', 'ClassicalGenre')
        keys = ['name']
        tags = ['Name']
        genre_dict_list = create_dict_from_ref_list(options, release_id, genre_list, keys, tags)

    except IOError:
        if options['cwp_muso_genres'] or options['cwp_muso_classical'] or options['cwp_muso_dates'] or options['cwp_muso_periods']:
            write_log(release_id, 'error', 'File %s does not exist or is corrupted', os.path.join(path, file))
    finally:
        return {'composers': composer_dict_list, 'periods': period_dict_list, 'genres': genre_dict_list}

prefixes = ['the', 'a', 'an', 'le', 'la', 'les', 'los', 'il']

PRESERVE = [x.strip() for x in config.setting["preserved_tags"].split(',')]
DATE_SEP = '-'

RELATION_TYPES = {
    'work': [
        'arranger',
        'instrument arranger',
        'orchestrator',
        'composer',
        'writer',
        'lyricist',
        'librettist',
        'revised by',
        'translator',
        'reconstructed by',
        'vocal arranger'],
    'release': [
        'instrument',
        'performer',
        'vocal',
        'performing orchestra',
        'conductor',
        'chorus master',
        'concertmaster',
        'arranger',
        'instrument arranger',
        'orchestrator',
        'vocal arranger'],
    'recording': [
        'instrument',
        'performer',
        'vocal',
        'performing orchestra',
        'conductor',
        'chorus master',
        'concertmaster',
        'arranger',
        'instrument arranger',
        'orchestrator',
        'vocal arranger']}

# OPTIONS

def get_options(release_id, album, track):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param album: current release
    :param track: current track
    :return: None (result is passed via tm)
    A common function for both Artist and Workparts, so that the first class to process a track will execute
    this function so that the results are available to both (via a track metadata item)
    """
    release_status[release_id]['done'] = False
    set_options = collections.defaultdict(dict)
    sections = ['artists', 'workparts']
    override = {
        'artists': 'cea_override',
        'tagmap': 'ce_tagmap_override',
        'workparts': 'cwp_override',
        'genres': 'ce_genres_override'}
    sect_text = {'artists': 'Artists', 'workparts': 'Works'}
    prefix = {'artists': 'cea', 'workparts': 'cwp'}

    if album.tagger.config.setting['ce_options_overwrite'] and all(
            album.tagger.config.setting[override[sect]] for sect in sections):
        set_options[track] = album.tagger.config.setting  # mutable
    else:
        set_options[track] = option_settings(
            album.tagger.config.setting)  # make a copy
        write_log(release_id, 'info', 'Default (i.e. per UI) options for track %s are %r', track, set_options[track])

    # As we use some of the main Picard options and may over-write them, save them here
    # set_options[track]['translate_artist_names'] = config.setting['translate_artist_names']
    # set_options[track]['standardize_artists'] = config.setting['standardize_artists']

    options = set_options[track]
    tm = track.metadata
    new_metadata = None
    orig_metadata = None
    # Only look up files if needed
    file_options = {}
    music_file = ''
    music_file_found = None
    release_status[release_id]['file_found'] = False
    start = datetime.now()
    write_log(release_id, 'info', 'Clock start at %s', start)
    trackno = tm['tracknumber']
    discno = tm['discnumber']

    album_filenames = album.tagger.get_files_from_objects([album])
    write_log(release_id, 'info', 'No. of album files found = %s', len(album_filenames))
    # Note that sometimes Picard fails to get all the file objects, even if they are there (network issues)
    # so we will cache whatever we can get!
    if release_id in release_status and 'file_objects' in release_status[release_id]:
        add_list_uniquely(release_status[release_id]['file_objects'], album_filenames)
    else:
        release_status[release_id]['file_objects'] = album_filenames
    write_log(release_id, 'info', 'No. of album files cached = %s', len(release_status[release_id]['file_objects']))
    track_file = None
    for album_file in release_status[release_id]['file_objects']:
        write_log(release_id, 'info', 'Track file = %s, tracknumber = %s, discnumber = %s. Metadata trackno = %s, discno = %s',
                  album_file.filename, str(album_file.tracknumber), str(album_file.discnumber), trackno, discno)
        if str(album_file.tracknumber) == trackno and str(album_file.discnumber) == discno:
            write_log(release_id, 'info', 'Track file found = %r', album_file.filename)
            track_file = album_file.filename
            break


    # Note: It would have been nice to do a rough check beforehand of total tracks,
    # but ~totalalbumtracks is not yet populated
    if not track_file:
        album_fullnames = [x.filename for x in release_status[release_id]['file_objects']]
        write_log(release_id, 'info', 'Album files found = %r', album_fullnames)
        for music_file in album_fullnames:
            new_metadata = album.tagger.files[music_file].metadata

            if 'musicbrainz_trackid' in new_metadata and 'musicbrainz_trackid' in tm:
                if new_metadata['musicbrainz_trackid'] == tm['musicbrainz_trackid']:
                    track_file = music_file
                    break
        # Nothing found...
        if new_metadata and 'musicbrainz_trackid' not in new_metadata:
            if options['log_warning']:
                write_log(release_id, 'warning', 'No trackid in file %s', music_file)
        if 'musicbrainz_trackid' not in tm:
            if options['log_warning']:
                write_log(release_id, 'warning', 'No trackid in track %s', track)
    """ 
    Note that, on initial load, new_metadata == orig_metadata; but, after refresh, new_metadata will have 
    the same track metadata as tm (plus the file metadata as per orig_metadata), so a trackid match
    is then possible for files that do not have musicbrainz_trackid in orig_metadata. That is why 
    new_metadata is used in the above test, rather than orig_metadata, but orig_metadata is then used below
    to get the saved options.
    """

    # Find the tag with the options:-
    if track_file:
        orig_metadata = album.tagger.files[track_file].orig_metadata
        music_file_found = track_file
        if options['log_info']:
            write_log(release_id, 'info', 'orig_metadata for file %s is', music_file)
            write_log(release_id, 'info', orig_metadata)
        for section in sections:
            if options[override[section]]:
                if options[prefix[section] + '_options_tag'] + ':' + \
                        section + '_options' in orig_metadata:
                    file_options[section] = interpret(
                        orig_metadata[options[prefix[section] + '_options_tag'] + ':' + section + '_options'])
                elif options[prefix[section] + '_options_tag'] in orig_metadata:
                    options_tag_contents = orig_metadata[options[prefix[section] + '_options_tag']]
                    if isinstance(options_tag_contents, list):
                        options_tag_contents = options_tag_contents[0]
                    combined_options = ''.join(options_tag_contents.split(
                        '(workparts_options)')).split('(artists_options)')
                    for i, _ in enumerate(combined_options):
                        combined_options[i] = interpret(
                            combined_options[i].lstrip('; '))
                        if isinstance(
                                combined_options[i],
                                dict) and 'Classical Extras' in combined_options[i]:
                            if sect_text[section] + \
                                    ' options' in combined_options[i]['Classical Extras']:
                                file_options[section] = combined_options[i]
                else:
                    for om in orig_metadata:
                        if ':' + section + '_options' in om:
                            file_options[section] = interpret(
                                orig_metadata[om])
                if section not in file_options or not file_options[section]:
                    if options['log_error']:
                        write_log(release_id, 'error', 'Saved ' +
                                  section +
                                  ' options cannot be read for file %s. Using current settings',
                                  music_file)
                    append_tag(release_id, tm, '~' + prefix[section] + '_error', '1. Saved ' +
                               section +
                               ' options cannot be read. Using current settings')

        release_status[release_id]['file_found'] = True

    end = datetime.now()
    if options['log_info']:
        write_log(release_id, 'info', 'Clock end at %s', end)
        write_log(release_id, 'info', 'Duration = %s', end - start)

    if not release_status[release_id]['file_found']:
        if options['log_warning']:
            write_log(release_id, 'warning',
                      "No file with matching trackid for track %s. IF THERE SHOULD BE ONE, TRY 'REFRESH'", track)
        append_tag(release_id, tm, "002_important_warning",
                   "No file with matching trackid - IF THERE SHOULD BE ONE, TRY 'REFRESH' - "
                   "(unable to process any saved options, lyrics or 'keep' tags)")
        # Nothing else is done with this info as yet - ideally we need to refresh and re-run
        # for all releases where release_status[release_id]['file_prob'] == True

    else:
        if options['log_info']:
            write_log(release_id, 'info', 'Found music file: %r', music_file_found)
        for section in sections:
            if options[override[section]]:
                if section in file_options and file_options[section]:
                    try:
                        options_dict = file_options[section]['Classical Extras'][sect_text[section] + ' options']
                    except TypeError:
                        if options['log_error']:
                            write_log(release_id, 'error', 'Saved ' +
                                      section +
                                      ' options cannot be read for file %s. Using current settings',
                                      music_file)
                        append_tag(release_id, tm, '~' + prefix[section] + '_error', '1. Saved ' +
                                   section +
                                   ' options cannot be read. Using current settings')
                        break
                    for opt in options_dict:
                        if isinstance(
                                options_dict[opt],
                                dict) and options[override['tagmap']]:  # for tag line options
                            # **NB tag mapping lines are the only entries of type dict**
                            opt_list = []
                            for opt_item in options_dict[opt]:
                                opt_list.append(
                                    {opt + '_' + opt_item: options_dict[opt][opt_item]})
                        else:
                            opt_list = [{opt: options_dict[opt]}]
                        for opt_dict in opt_list:
                            for opt_det in opt_dict:
                                opt_value = opt_dict[opt_det]
                                if section == 'artists':
                                    if options[override['tagmap']]:
                                        included_tag_options = plugin_options('tag')
                                    else:
                                        included_tag_options = []
                                    addn = included_tag_options + plugin_options('picard')
                                else:
                                    if options[override['genres']]:
                                        included_genre_options = plugin_options('genres')
                                    else:
                                        included_genre_options = []
                                    addn = included_genre_options
                                for ea_opt in plugin_options(section) + addn:
                                    displayed_option = options[ea_opt['option']]
                                    if ea_opt['name'] == opt_det:
                                        if 'value' in ea_opt:
                                            if ea_opt['value'] == opt_value:
                                                options[ea_opt['option']] = True
                                            else:
                                                options[ea_opt['option']] = False
                                        else:
                                            options[ea_opt['option']] = opt_value
                                        if options[ea_opt['option']
                                                   ] != displayed_option:
                                            if options['log_debug']:
                                                write_log(release_id, 'debug', 'Options overridden for option %s = %s',
                                                          ea_opt['option'], opt_value)

                                            opt_text = unicode(opt_value)
                                            append_tag(release_id, tm, '003_information:options_overridden', unicode(
                                                ea_opt['name']) + ' = ' + opt_text)

        if orig_metadata:
            keep_list = options['cea_keep'].split(",")
            if options['cea_split_lyrics'] and options['cea_lyrics_tag']:
                keep_list.append(options['cea_lyrics_tag'])
            if options['cwp_genres_use_file'] and options['cwp_genre_tag']:
                keep_list.append(options['cwp_genre_tag'])
            PRESERVE.append(options['cwp_options_tag'] + ':workparts_options')
            PRESERVE.append(options['cea_options_tag'] + ':artists_options')
            really_keep_list = PRESERVE
            for tagx in keep_list:
                tag = tagx.strip()
                really_keep_list.append(tag)
                if tag in orig_metadata:
                    tm[tag] = orig_metadata[tag]
            if options['cea_clear_tags']:
                delete_list = []
                for tag_item in orig_metadata:
                    if tag_item not in really_keep_list and tag_item[0] != '~':
                        # the second condition is to ensure that (hidden) file variables are not deleted,
                        #  as these are in orig_metadata, not track_metadata
                        delete_list.append(tag_item)
                # this will be used in map_tags to delete unwanted tags
                options['delete_tags'] = delete_list
        if not isinstance(options, dict):
            options_dict = option_settings(config.setting)
        else:
            options_dict = options
        tm['~ce_options'] = options_dict
        tm['~ce_file'] = music_file_found
        if options['log_info']:
            write_log(release_id, 'info', 'Get_options is returning options shown below for file: %s', music_file_found)
            write_log(release_id, 'info', options_dict)


def plugin_options(option_type):
    """
    :param option_type: artists, tag, workparts, genres or other
    :return: the relevant dictionary for the type
    This function contains all the options data in one place - to prevent multiple repetitions elsewhere
    """

    # artists options (excluding tag mapping lines)
    artists_options = [
        {'option': 'classical_extra_artists',
         'name': 'run extra artists',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_orchestras',
         'name': 'orchestra strings',
         'type': 'Text',
         'default': 'orchestra, philharmonic, philharmonica, philharmoniker, musicians, academy, symphony, orkester'
         },
        {'option': 'cea_choirs',
         'name': 'choir strings',
         'type': 'Text',
         'default': 'choir, choir vocals, chorus, singers, domchors, domspatzen, koor, kammerkoor'
         },
        {'option': 'cea_groups',
         'name': 'group strings',
         'type': 'Text',
         'default': 'ensemble, band, group, trio, quartet, quintet, sextet, septet, octet, chamber, consort, players, '
                    'les ,the , quartett'
         },
        {'option': 'cea_aliases',
         'name': 'replace artist name with alias?',
         'value': 'replace',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_aliases_composer',
         'name': 'replace artist name with alias?',
         'value': 'composer',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_no_aliases',
         'name': 'replace artist name with alias?',
         'value': 'no replace',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_alias_overrides',
         'name': 'alias vs credited-as',
         'value': 'alias over-rides',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_credited_overrides',
         'name': 'alias vs credited-as',
         'value': 'credited-as over-rides',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_ra_use',
         'name': 'use recording artist',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_ra_trackartist',
         'name': 'recording artist name style',
         'value': 'track artist',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_ra_performer',
         'name': 'recording artist name style',
         'value': 'performer',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_ra_replace_ta',
         'name': 'recording artist effect on track artist',
         'value': 'replace',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_ra_noblank_ta',
         'name': 'disallow blank recording artist',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_ra_merge_ta',
         'name': 'recording artist effect on track artist',
         'value': 'merge',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_composer_album',
         'name': 'Album prefix',
         # 'value': 'Composer', # Can't use 'value' if there is only one option, otherwise False will revert to default
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_blank_tag',
         'name': 'Tags to blank',
         'type': 'Text',
         'default': 'artist, artistsort'
         },
        {'option': 'cea_blank_tag_2',
         'name': 'Tags to blank 2',
         'type': 'Text',
         'default': 'performer:orchestra, performer:choir, performer:choir vocals'
         },
        {'option': 'cea_keep',
         'name': 'File tags to keep',
         'type': 'Text',
         'default': 'is_classical'
         },
        {'option': 'cea_clear_tags',
         'name': 'Clear previous tags',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_arrangers',
         'name': 'include arrangers',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_no_lyricists',
         'name': 'exclude lyricists if no vocals',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_cyrillic',
         'name': 'fix cyrillic',
         'type': 'Boolean',
         'default': True
         },
        # {'option': 'cea_genres',
        #  'name': 'infer work types',
        #  'type': 'Boolean',
        #  'default': True
        #  },
        # Note that the above is no longer used - replaced by cwp_genres_infer from v0.9.2
        {'option': 'cea_credited',
         'name': 'use release credited-as name',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_release_relationship_credited',
         'name': 'use release relationship credited-as name',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_group_credited',
         'name': 'use release-group credited-as name',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_recording_credited',
         'name': 'use recording credited-as name',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_recording_relationship_credited',
         'name': 'use recording relationship credited-as name',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_track_credited',
         'name': 'use track credited-as name',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_performer_credited',
         'name': 'use credited-as name for performer',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_composer_credited',
         'name': 'use credited-as name for composer',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cea_inst_credit',
         'name': 'use credited instrument',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_no_solo',
         'name': 'exclude solo',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_chorusmaster',
         'name': 'chorusmaster',
         'type': 'Text',
         'default': 'choirmaster'
         },
        {'option': 'cea_orchestrator',
         'name': 'orchestrator',
         'type': 'Text',
         'default': 'orch.'
         },
        {'option': 'cea_concertmaster',
         'name': 'concertmaster',
         'type': 'Text',
         'default': 'leader'
         },
        {'option': 'cea_lyricist',
         'name': 'lyricist',
         'type': 'Text',
         'default': ''
         },
        {'option': 'cea_librettist',
         'name': 'librettist',
         'type': 'Text',
         'default': 'libretto'
         },
        {'option': 'cea_writer',
         'name': 'writer',
         'type': 'Text',
         'default': 'writer'
         },
        {'option': 'cea_arranger',
         'name': 'arranger',
         'type': 'Text',
         'default': 'arr.'
         },
        {'option': 'cea_reconstructed',
         'name': 'reconstructed by',
         'type': 'Text',
         'default': 'reconstructed'
         },
        {'option': 'cea_revised',
         'name': 'revised by',
         'type': 'Text',
         'default': 'revised'
         },
        {'option': 'cea_translator',
         'name': 'translator',
         'type': 'Text',
         'default': 'trans.'
         },
        {'option': 'cea_split_lyrics',
         'name': 'split lyrics',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cea_lyrics_tag',
         'name': 'lyrics',
         'type': 'Text',
         'default': 'lyrics'
         },
        {'option': 'cea_album_lyrics',
         'name': 'album lyrics',
         'type': 'Text',
         'default': 'albumnotes'
         },
        {'option': 'cea_track_lyrics',
         'name': 'track lyrics',
         'type': 'Text',
         'default': 'tracknotes'
         },
        {'option': 'cea_tag_sort',
         'name': 'populate sort tags',
         'type': 'Boolean',
         'default': True
         }
    ]

    #  tag mapping lines
    default_list = [
        ('album_soloists, album_ensembles, album_conductors', 'artist, artists', False),
        ('recording_artists', 'artist, artists', True),
        ('soloist_names, ensemble_names, conductors', 'artist, artists', True),
        ('soloists', 'soloists, trackartist', False),
        ('release', 'release_name', False),
        ('work_type', 'genre', False),
        ('ensemble_names', 'band', False),
        ('composers', 'artist', True),
        ('MB_artists', 'composer', True),
        ('arranger', 'composer', True)
    ]
    tag_options = []
    for i in range(0, 16):
        if i < len(default_list):
            default_source, default_tag, default_cond = default_list[i]
        else:
            default_source = ''
            default_tag = ''
            default_cond = False
        tag_options.append({'option': 'cea_source_' + unicode(i + 1),
                            'name': 'line ' + unicode(i + 1) + '_source',
                            'type': 'Combo',
                            'default': default_source
                            })
        tag_options.append({'option': 'cea_tag_' + unicode(i + 1),
                            'name': 'line ' + unicode(i + 1) + '_tag',
                            'type': 'Text',
                            'default': default_tag
                            })
        tag_options.append({'option': 'cea_cond_' + unicode(i + 1),
                            'name': 'line ' + unicode(i + 1) + '_conditional',
                            'type': 'Boolean',
                            'default': default_cond
                            })

    # workparts options
    workparts_options = [
        {'option': 'classical_work_parts',
         'name': 'run work parts',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_collections',
         'name': 'include collection relations',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_proximity',
         # proximity of new words in title comparison which will result in
         # infill words being included as well. 2 means 2-word 'gaps' of
         # existing words between new words will be treated as 'new'
         'name': 'in-string proximity trigger',
         'type': 'Integer',
         'default': 2
         },
        {'option': 'cwp_end_proximity',
         # proximity measure to be used when infilling to the end of the title
         'name': 'end-string proximity trigger',
         'type': 'Integer',
         'default': 1
         },
        {'option': 'cwp_granularity',
         # splitting for matching of parents. 1 = split in two, 2 = split in
         # three etc.
         'name': 'work-splitting',
         'type': 'Integer',
         'default': 1
         },
        {'option': 'cwp_substring_match',
         # Proportion of a string to be matched to a (usually larger) string for
         # it to be considered essentially similar
         'name': 'similarity threshold',
         'type': 'Integer',
         'default': 66
         },
        {'option': 'cwp_removewords',
         'name': 'ignore prefixes',
         'type': 'Text',
         'default': ' part, act, scene, movement, movt, no., no , n., n , nr., nr , book , the , a , la , le , un ,'
                    ' une , el , il , (part), tableau, from '
         },
        {'option': 'cwp_synonyms',
         'name': 'synonyms',
         'type': 'Text',
         'default': '(1, one) / (2, two) / (3, three) / (&, and) / (Rezitativ, Recitativo) / '
                    '(Recitativo, Recitative) / (Arie, Aria)'
         },
        {'option': 'cwp_replacements',
         'name': 'replacements',
         'type': 'Text',
         'default': '(words to be replaced, replacement words) / (please blank me, ) / (etc, etc)'
         },
        {'option': 'cwp_titles',
         'name': 'Style',
         'value': 'Titles',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_works',
         'name': 'Style',
         'value': 'Works',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_extended',
         'name': 'Style',
         'value': 'Extended',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_hierarchical_works',
         'name': 'Work source',
         'value': 'Hierarchy',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_level0_works',
         'name': 'Work source',
         'value': 'Level_0',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_movt_tag_inc',
         'name': 'movement tag inc num',
         'type': 'Text',
         'default': 'part, movement name, subtitle'
         },
        {'option': 'cwp_movt_tag_exc',
         'name': 'movement tag exc num',
         'type': 'Text',
         'default': 'movement'
         },
        {'option': 'cwp_movt_tag_inc1',
         'name': '1-level movement tag inc num',
         'type': 'Text',
         'default': ''
         },
        {'option': 'cwp_movt_tag_exc1',
         'name': '1-level movement tag exc num',
         'type': 'Text',
         'default': ''
         },
        {'option': 'cwp_movt_no_tag',
         'name': 'movement num tag',
         'type': 'Text',
         'default': 'movement_no'
         },
        {'option': 'cwp_work_tag_multi',
         'name': 'multi-level work tag',
         'type': 'Text',
         'default': 'groupheading, work'
         },
        {'option': 'cwp_work_tag_single',
         'name': 'single level work tag',
         'type': 'Text',
         'default': ''
         },
        {'option': 'cwp_top_tag',
         'name': 'top level work tag',
         'type': 'Text',
         'default': 'top_work, style, grouping'
         },
        {'option': 'cwp_multi_work_sep',
         'name': 'multi-level work separator',
         'type': 'Combo',
         'default': ':'
         },
        {'option': 'cwp_single_work_sep',
         'name': 'single level work separator',
         'type': 'Combo',
         'default': ':'
         },
        {'option': 'cwp_movt_no_sep',
         'name': 'movement number separator',
         'type': 'Combo',
         'default': '.'
         },
        {'option': 'cwp_partial',
         'name': 'show partial recordings',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_partial_text',
         'name': 'partial text',
         'type': 'Text',
         'default': '(part)'
         },
        {'option': 'cwp_arrangements',
         'name': 'include arrangement of',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_arrangements_text',
         'name': 'arrangements text',
         'type': 'Text',
         'default': 'Arrangement:'
         },
        {'option': 'cwp_medley',
         'name': 'list medleys',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_medley_text',
         'name': 'medley text',
         'type': 'Text',
         'default': 'Medley of:'
         }
    ]
    # Options on "Genres etc." tab

    genre_options = [
        {'option': 'cwp_genre_tag',
         'name': 'main genre tag',
         'type': 'Text',
         'default': 'genre'
         },
        {'option': 'cwp_subgenre_tag',
         'name': 'sub-genre tag',
         'type': 'Text',
         'default': 'sub-genre'
         },
        {'option': 'cwp_genres_use_file',
         'name': 'source genre from file',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_genres_use_folks',
         'name': 'source genre from folksonomy tags',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_genres_use_worktype',
         'name': 'source genre from work-type(s)',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_genres_infer',
         'name': 'infer genre from artist details(s)',
         'type': 'Boolean',
         'default': False
         },
        # Note that the "infer from artists" option was in  the "artists" section - legacy from v0.9.1 & prior
        {'option': 'cwp_genres_classical_main',
         'name': 'classical main genres',
         'type': 'PlainText',
         'default': 'Classical, Chamber music, Concerto, Symphony, Opera, Orchestral, Sonata, Choral, Aria, Ballet, '
                    'Oratorio, Motet, Symphonic poem, Suite, Partita, Song-cycle, Overture, '
                    'Mass, Cantata'
         },
        {'option': 'cwp_genres_classical_sub',
         'name': 'classical main genres',
         'type': 'PlainText',
         'default': 'Chant, Classical crossover, Minimalism, Avant-garde, Impressionist, Aria, Duet, Trio, Quartet'
         },
        {'option': 'cwp_genres_other_main',
         'name': 'general main genres',
         'type': 'PlainText',
         'default': 'Alternative music, Blues, Country, Dance, Easy listening, Electronic music, Folk, Folk / pop, '
                    'Hip hop / rap, Indie,  Religious, Asian, Jazz, Latin, New age, Pop, R&B / Soul, Reggae, Rock, '
                    'World music, Celtic folk, French Medieval'
         },
        {'option': 'cwp_genres_other_sub',
         'name': 'general sub-genres',
         'type': 'PlainText',
         'default': 'Song, Vocal, Christmas, Instrumental'
         },
        {'option': 'cwp_genres_arranger_as_composer',
         'name': 'treat arranger as for composer for genre-setting',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_genres_classical_all',
         'name': 'make tracks classical',
         'value': 'all',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_genres_classical_selective',
         'name': 'make tracks classical',
         'value': 'selective',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_genres_classical_exclude',
         'name': 'exclude "classical" from main genre tag',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_genres_flag_text',
         'name': 'classical flag',
         'type': 'Text',
         'default': '1'
         },
        {'option': 'cwp_genres_flag_tag',
         'name': 'classical flag tag',
         'type': 'Text',
         'default': 'is_classical'
         },
        {'option': 'cwp_genres_default',
         'name': 'default genre',
         'type': 'Text',
         'default': 'Other'
         },
        {'option': 'cwp_instruments_tag',
         'name': 'instruments tag',
         'type': 'Text',
         'default': 'instrument'
         },
        {'option': 'cwp_instruments_MB_names',
         'name': 'use MB instrument names',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_instruments_credited_names',
         'name': 'use credited instrument names',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_key_tag',
         'name': 'key tag',
         'type': 'Text',
         'default': 'key'
         },
        {'option': 'cwp_key_include',
         'name': 'include key in workname',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_workdate_tag',
         'name': 'workdate tag',
         'type': 'Text',
         'default': 'work_year'
         },
        {'option': 'cwp_workdate_source_composed',
         'name': 'use composed for workdate',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_workdate_source_published',
         'name': 'use published for workdate',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_workdate_source_premiered',
         'name': 'use premiered for workdate',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_workdate_use_first',
         'name': 'use workdate sources sequentially',
         'value': 'sequence',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_workdate_use_all',
         'name': 'use all workdate sources',
         'value': 'all',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_workdate_annotate',
         'name': 'annotate dates',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_workdate_include',
         'name': 'include workdate in workname',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_period_tag',
         'name': 'period tag',
         'type': 'Text',
         'default': 'period'
         },
        {'option': 'cwp_periods_arranger_as_composer',
         'name': 'treat arranger as for composer for period-setting',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_period_map',
         'name': 'period map',
         'type': 'PlainText',
         'default': 'Early, -3000,800; Medieval, 800,1400; Renaissance, 1400, 1600; Baroque, 1600,1750; '
                    'Classical, 1750,1820; Early Romantic, 1800,1850; Late Romantic, 1850,1910; '
                    '20th Century, 1910,1975; Contemporary, 1975,2525'
         }
    ]
    # Picard options which are also saved
    picard_options = [
        {'option': 'standardize_artists',
         'name': 'standardize artists',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'translate_artist_names',
         'name': 'translate artist names',
         'type': 'Boolean',
         'default': True
         },
    ]

    # other options (not saved in file tags)
    other_options = [
        {'option': 'use_cache',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_aliases',
         'name': 'replace with alias?',
         'value': 'replace',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_no_aliases',
         'name': 'replace with alias?',
         'value': 'no replace',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_aliases_all',
         'name': 'alias replacement type',
         'value': 'all',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_aliases_greek',
         'name': 'alias replacement type',
         'value': 'non-latin',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_aliases_tagged',
         'name': 'alias replacement type',
         'value': 'tagged works',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_aliases_tag_text',
         'name': 'use_alias tag text',
         'type': 'Text',
         'default': 'use_alias'
         },
        {'option': 'cwp_aliases_tags_all',
         'name': 'use_alias tags all',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'cwp_aliases_tags_user',
         'name': 'use_alias tags user',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_use_sk',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_write_sk',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_retries',
         'type': 'Integer',
         'default': 6
         },
        {'option': 'cwp_use_muso_refdb',
         'name': 'use Muso ref database',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_muso_genres',
         'name': 'use Muso classical genres',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_muso_classical',
         'name': 'use Muso classical composers',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_muso_dates',
         'name': 'use Muso composer dates',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_muso_periods',
         'name': 'use Muso periods',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_muso_path',
         'name': 'path to Muso database',
         'type': 'Text',
         'default': 'C:\\Users\\Public\\Music\\muso\\database'
         },
        {'option': 'cwp_muso_refdb',
         'name': 'name of Muso reference database',
         'type': 'Text',
         'default': 'Reference.xml'
         },
                {'option': 'log_error',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'log_warning',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'log_debug',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'log_basic',
         'type': 'Boolean',
         'default': True
         },
        {'option': 'log_info',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'ce_version_tag',
         'type': 'Text',
         'default': 'stamp'
         },
        {'option': 'cea_options_tag',
         'type': 'Text',
         'default': 'comment'
         },
        {'option': 'cwp_options_tag',
         'type': 'Text',
         'default': 'comment'
         },
        {'option': 'cea_override',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'ce_tagmap_override',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'cwp_override',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'ce_genres_override',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'ce_options_overwrite',
         'type': 'Boolean',
         'default': False
         },
        {'option': 'ce_no_run',
         'type': 'Boolean',
         'default': False
         }
    ]

    if option_type == 'artists':
        return artists_options
    elif option_type == 'tag':
        return tag_options
    elif option_type == 'workparts':
        return workparts_options
    elif option_type == 'genres':
        return genre_options
    elif option_type == 'picard':
        return picard_options
    elif option_type == 'other':
        return other_options
    else:
        return None


def option_settings(config_settings):
    """
    :param config_settings: options from UI
    :return: a (deep) copy of the Classical Extras options
    """
    options = {}
    for option in plugin_options('artists') + plugin_options('tag') + plugin_options(
            'workparts') + plugin_options('genres') + plugin_options('picard') + plugin_options('other'):
        options[option['option']] = copy.deepcopy(
            config_settings[option['option']])
    return options


def get_aliases(self, release_id, album, options, releaseXmlNode):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param self:
    :param album:
    :param options:
    :param releaseXmlNode: all the metadata for the release
    :return: Data is returned via self.artist_aliases and self.artist_credits[album]

    Note regarding aliases and credited-as names:
    In a MB release, an artist can appear in one of seven contexts. Each of these is accessible in releaseXmlNode
    and the track and recording contexts are also accessible in trackXmlNode.
    The seven contexts are:
    Release-group: credited-as and alias
    Release: credited-as and alias
    Release relationship: credited-as only
    Recording: credited-as and alias
    Recording relationship (direct): credited-as only
    Recording relationship (via work): credited-as only
    Track: credited-as and alias
    (The above are applied in sequence - e.g. track artist credit will over-ride release artist credit)
    This function collects all the available aliases and as-credited names once (on processing the first track).
    N.B. if more than one release is loaded in Picard, any available alias names loaded so far will be available
    and used. However, as-credited names will only be used from the current release."""

    if 'artist_locale' in config.setting and options['cea_aliases'] or options['cea_aliases_composer']:
        locale = config.setting["artist_locale"]
        lang = locale.split("_")[0]  # NB this is the Picard code in /util

        # Release group artists
        obj = parse_data(release_id, releaseXmlNode, [], 'release_group')
        get_aliases_and_credits(self, options, release_id, album, obj, lang, options['cea_group_credited'])

        # Release artists
        get_aliases_and_credits(self, options, release_id, album, releaseXmlNode, lang, options['cea_credited'])
        # Next bit needed to identify artists who are album artists
        self.release_artists_sort[album] = parse_data(release_id, releaseXmlNode, [], 'artist_credit', 'name_credit',
                                                      'artist', 'sort_name', 'text')
        # Release relationship artists (credits only)
        if options['cea_release_relationship_credited']:
            get_relation_credits(self, options, release_id, album, releaseXmlNode)

        # Track and recording aliases/credits are gathered by parsing the
        # media, track and recording nodes
        media = parse_data(release_id, releaseXmlNode, [], 'medium_list', 'medium')
        for m in media:
            # disc_num = int(parse_data(options, m, [], 'position', 'text')[0])
            # not currently used
            tracks = parse_data(release_id, m, [], 'track_list', 'track')
            for tlist in tracks:
                for t in tlist:
                    # track_num = int(parse_data(options, t, [], 'number',
                    # 'text')[0]) # not currently used
                    obj = parse_data(release_id, t, [], 'recording')
                    get_aliases_and_credits(self, options, release_id, album, obj, lang,
                                            options['cea_recording_credited'])  # recording artists
                    if options['cea_recording_relationship_credited']:
                        # recording relationship artists (credits only)
                        get_relation_credits(self, options, release_id, album, obj)
                    get_aliases_and_credits(self, options, release_id, album, t, lang,
                                            options['cea_track_credited'])  # track artists
    if options['log_info']:
        write_log(release_id, 'info', 'Alias and credits info for %s', self)
        write_log(release_id, 'info', 'Aliases :%s', self.artist_aliases)
        write_log(release_id, 'info', 'Credits :%s', self.artist_credits[album])


def get_artists(options, release_id, tm, relations, relation_type):
    """
    Get artist info from XML lookup
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param options:
    :param tm:
    :param relations:
    :param relation_type: 'release', 'recording' or 'work' (NB 'work' does not pass a param for tm)
    :return:
    """
    log_options = {
        'log_debug': options['log_debug'],
        'log_info': options['log_info']}
    artists = []
    instruments = []
    artist_types = RELATION_TYPES[relation_type]
    for artist_type in artist_types:
        type_list = parse_data(release_id, relations, [], 'attribs.target_type:artist', 'relation', 'attribs.type:' +
                               artist_type)
        for type_item in type_list:
            artist_name_list = parse_data(release_id, type_item, [], 'direction.text:backward', 'artist', 'name',
                                          'text')
            artist_sort_name_list = parse_data(release_id, type_item, [], 'direction.text:backward', 'artist',
                                               'sort_name', 'text')
            if artist_type not in [
                'instrument',
                'vocal',
                'instrument arranger',
                    'vocal arranger']:
                instrument_list = None
                credited_inst_list = None
            else:
                instrument_list = []
                credited_inst_list = []
                att_list = parse_data(release_id, type_item, [], 'direction.text:backward', 'attribute_list',
                                      'attribute')
                for inst_nodes in att_list:
                    for inst_node in inst_nodes:
                        cred_list = parse_data(release_id, inst_node, [], 'attribs.credited_as')
                        inst_list = parse_data(release_id, inst_node, [], 'text')
                        if cred_list:
                            credited_inst_list += cred_list
                        else:
                            credited_inst_list += inst_list
                        instrument_list += inst_list
                if artist_type == 'vocal':
                    if not instrument_list:
                        instrument_list = ['vocals']
                    elif not any('vocals' in x for x in instrument_list):
                        instrument_list.append('vocals')
                        credited_inst_list.append('vocals')
            # fill the hidden vars before we choose to use the as-credited
            # version
            if relation_type != 'work':
                inst_tag = []
                cred_tag = []
                if instrument_list:
                    if options['log_info']:
                        write_log(release_id, 'info', 'instrument_list: %s', instrument_list)
                    inst_tag = list(set(instrument_list))
                if credited_inst_list:
                    cred_tag = list(set(credited_inst_list))
                for attrib in ['solo', 'guest', 'additional']:
                    if attrib in inst_tag:
                        inst_tag.remove(attrib)
                    if attrib in cred_tag:
                        cred_tag.remove(attrib)
                if inst_tag:
                    if tm['~cea_instruments']:
                        tm['~cea_instruments'] = add_list_uniquely(
                            tm['~cea_instruments'], inst_tag)
                    else:
                        tm['~cea_instruments'] = inst_tag
                if cred_tag:
                    if tm['~cea_instruments_credited']:
                        tm['~cea_instruments_credited'] = add_list_uniquely(
                            tm['~cea_instruments_credited'], cred_tag)
                    else:
                        tm['~cea_instruments_credited'] = cred_tag
                if inst_tag or cred_tag:
                    if tm['~cea_instruments_all']:
                        tm['~cea_instruments_all'] = add_list_uniquely(
                            tm['~cea_instruments_all'], list(set(inst_tag + cred_tag)))
                    else:
                        tm['~cea_instruments_all'] = list(
                            set(inst_tag + cred_tag))
            if '~cea_instruments' in tm and '~cea_instruments_credited' in tm and '~cea_instruments_all' in tm:
                instruments = [
                    tm['~cea_instruments'],
                    tm['~cea_instruments_credited'],
                    tm['~cea_instruments_all']]
            if options['cea_inst_credit'] and credited_inst_list:
                instrument_list = credited_inst_list
            if instrument_list:
                instrument_sort = 3
                s_key = {
                    'lead vocals': 1,
                    'solo': 2,
                    'guest': 4,
                    'additional': 5}
                for inst in s_key:
                    if inst in instrument_list:
                        instrument_sort = s_key[inst]
            else:
                instrument_sort = 0

            type_sort_dict = {'vocal': 1,
                              'instrument': 1,
                              'performer': 0,
                              'performing orchestra': 2,
                              'concertmaster': 3,
                              'conductor': 4,
                              'chorus master': 5,
                              'composer': 6,
                              'writer': 7,
                              'reconstructed by': 8,
                              'instrument arranger': 9,
                              'vocal arranger': 9,
                              'arranger': 11,
                              'orchestrator': 12,
                              'revised by': 13,
                              'lyricist': 14,
                              'librettist': 15,
                              'translator': 16
                              }
            if artist_type in type_sort_dict:
                type_sort = type_sort_dict[artist_type]
            else:
                type_sort = 99
                if log_options['log_error']:
                    write_log(release_id, 'error', "Error in artist type. Type '%s' is not in dictionary", artist_type)

            artist = (
                artist_type,
                instrument_list,
                artist_name_list,
                artist_sort_name_list,
                instrument_sort,
                type_sort)
            artists.append(artist)
            # Sorted by sort name then instrument_sort then artist type
            artists = sorted(artists, key=lambda x: (x[5], x[3], x[4], x[1]))
            if log_options['log_info']:
                write_log(release_id, 'info', 'sorted artists = %s', artists)
    artist_dict = {'artists': artists, 'instruments': instruments}
    return artist_dict


def apply_artist_style(options, release_id, lang, a_list, name_style, name_tag, sort_tag, names_tag, names_sort_tag):
    # Get  artist and apply style
    for acs in a_list:
        for ncs in acs:
            artistlist = parse_data(release_id, ncs, [], 'artist', 'name', 'text')
            sortlist = parse_data(release_id, ncs, [], 'artist', 'sort_name', 'text')
            names = {}
            if lang:
                names['alias'] = parse_data(release_id, ncs, [], 'artist', 'alias_list', 'alias', 'attribs.locale:' +
                                            lang, 'attribs.primary:primary', 'text')
            else:
                names['alias'] = []
            names['credit'] = parse_data(release_id, ncs, [], 'name', 'text')
            pairslist = zip(artistlist, sortlist)
            names['sort'] = [
                translate_from_sortname(
                    *pair) for pair in pairslist]
            for style in name_style:
                if names[style]:
                    artistlist = names[style]
                    break
            joinlist = parse_data(release_id, ncs, [], 'attribs.joinphrase')

            if artistlist:
                name_tag.append(artistlist[0])
                sort_tag.append(sortlist[0])
                names_tag.append(artistlist[0])
                names_sort_tag.append(sortlist[0])

            if joinlist:
                name_tag.append(joinlist[0])
                sort_tag.append(joinlist[0])

    name_tag_str = ''.join(name_tag)
    sort_tag_str = ''.join(sort_tag)

    return {
        'artists': names_tag,
        'artists_sort': names_sort_tag,
        'artist': name_tag_str,
        'artistsort': sort_tag_str}


def set_work_artists(self, release_id, album, track, writerList, tm, count):
    """
    :param release_id:
    :param self is the calling object from Artists or WorkParts
    :param album: the current album
    :param track: the current track
    :param writerList: format [(artist_type, [instrument_list], [name list],[sort_name list]),(.....etc]
    :param tm: track metatdata
    :param count: depth count of recursion in process_work_artists (should equate to part level)
    :return:
    """

    options = self.options[track]
    if not options['classical_work_parts']:
        caller = 'ExtraArtists'
        pre = '~cea'
    else:
        caller = 'PartLevels'
        pre = '~cwp'
    if self.DEBUG or self.INFO:
        write_log(release_id, 'debug',
                  'Class: %s: in set_work_artists for track %s. Count (level) is %s. Writer list is %s',
                  caller, track, count, writerList)
    # tag strings are a tuple (Picard tag, cwp tag, Picard sort tag, cwp sort
    # tag) (NB this is modelled on set_performer)
    tag_strings = {
        'writer': (
            'composer',
            pre + '_writers',
            'composersort',
            pre + '_writers_sort'),
        'composer': (
            'composer',
            pre + '_composers',
            'composersort',
            pre + '_composers_sort'),
        'lyricist': (
            'lyricist',
            pre + '_lyricists',
            '~lyricists_sort',
            pre + '_lyricists_sort'),
        'librettist': (
            'lyricist',
            pre + '_librettists',
            '~lyricists_sort',
            pre + '_librettists_sort'),
        'revised by': (
            'arranger',
            pre + '_revisors',
            '~arranger_sort',
            pre + '_revisors_sort'),
        'translator': (
            'lyricist',
            pre + '_translators',
            '~lyricists_sort',
            pre + '_translators_sort'),
        'reconstructed by': (
            'arranger',
            pre + '_reconstructors',
            '~arranger_sort',
            pre + '_reconstructors_sort'),
        'arranger': (
            'arranger',
            pre + '_arrangers',
            '~arranger_sort',
            pre + '_arrangers_sort'),
        'instrument arranger': (
            'arranger',
            pre + '_arrangers',
            '~arranger_sort',
            pre + '_arrangers_sort'),
        'orchestrator': (
            'arranger',
            pre + '_orchestrators',
            '~arranger_sort',
            pre + '_orchestrators_sort'),
        'vocal arranger': (
            'arranger',
            pre + '_arrangers',
            '~arranger_sort',
            pre + '_arrangers_sort')}
    # insertions lists artist types where names in the main Picard tags may be
    # updated for annotations
    insertions = ['writer',
                  'lyricist',
                  'librettist',
                  'revised by',
                  'translator',
                  'arranger',
                  'reconstructed by',
                  'orchestrator',
                  'instrument arranger',
                  'vocal arranger']
    no_more_lyricists = False
    if caller == 'PartLevels' and self.lyricist_filled[track]:
        no_more_lyricists = True

    for writer in writerList:
        writer_type = writer[0]
        if writer_type not in tag_strings:
            break
        if no_more_lyricists and (
                writer_type == 'lyricist' or writer_type == 'librettist'):
            break
        if writer[1]:
            inst_list = writer[1][:]
            # take a copy of the list in case (because of list
            # mutability) we need the old one
            instrument = ", ".join(inst_list)
        else:
            instrument = None
        sub_strings = {  # 'instrument arranger': instrument, 'vocal arranger': instrument
        }
        if options['cea_arranger']:
            if instrument:
                arr_inst = options['cea_arranger'] + ' ' + instrument
            else:
                arr_inst = options['cea_arranger']
        else:
            arr_inst = instrument
        annotations = {'writer': options['cea_writer'],
                       'lyricist': options['cea_lyricist'],
                       'librettist': options['cea_librettist'],
                       'revised by': options['cea_revised'],
                       'translator': options['cea_translator'],
                       'arranger': options['cea_arranger'],
                       'reconstructed by': options['cea_reconstructed'],
                       'orchestrator': options['cea_orchestrator'],
                       'instrument arranger': arr_inst,
                       'vocal arranger': arr_inst}
        tag = tag_strings[writer_type][0]
        sort_tag = tag_strings[writer_type][2]
        cwp_tag = tag_strings[writer_type][1]
        cwp_sort_tag = tag_strings[writer_type][3]
        cwp_names_tag = cwp_tag[:-1] + '_names'
        cwp_instrumented_tag = cwp_names_tag + '_instrumented'
        if writer_type in sub_strings:
            if sub_strings[writer_type]:
                tag += sub_strings[writer_type]
        if tag:
            if '~ce_tag_cleared_' + \
                    tag not in tm or not tm['~ce_tag_cleared_' + tag] == "Y":
                if tag in tm:
                    if options['log_info']:
                        write_log(release_id, 'info', 'delete tag %s', tag)
                    del tm[tag]
            tm['~ce_tag_cleared_' + tag] = "Y"
        if sort_tag:
            if '~ce_tag_cleared_' + \
                    sort_tag not in tm or not tm['~ce_tag_cleared_' + sort_tag] == "Y":
                if sort_tag in tm:
                    del tm[sort_tag]
            tm['~ce_tag_cleared_' + sort_tag] = "Y"

        name_list = writer[2]
        for ind, name in enumerate(name_list):
            sort_name = writer[3][ind]
            no_credit = True
            if self.INFO:
                write_log(release_id, 'info', 'In set_work_artists. Name before changes = %s', name)
            # change name to as-credited
            if options['cea_composer_credited']:
                if sort_name in self.artist_credits[album]:
                    no_credit = False
                    name = self.artist_credits[album][sort_name]
            # over-ride with aliases if appropriate
            if (options['cea_aliases'] or options['cea_aliases_composer']) and (
                    no_credit or options['cea_alias_overrides']):
                if sort_name in self.artist_aliases:
                    name = self.artist_aliases[sort_name]
            # fix cyrillic names if not already fixed
            if options['cea_cyrillic']:
                if not only_roman_chars(name):
                    name = remove_middle(unsort(sort_name))
                    # Only remove middle name where the existing
                    # performer is in non-latin script
            annotated_name = name
            if self.INFO:
                write_log(release_id, 'info', 'In set_work_artists. Name after changes = %s', name)
            # add annotations and write performer tags
            if writer_type in annotations:
                if annotations[writer_type]:
                    annotated_name += ' (' + annotations[writer_type] + ')'
            if instrument:
                instrumented_name = name + ' (' + instrument + ')'
            else:
                instrumented_name = name

            if writer_type in insertions and options['cea_arrangers']:
                self.append_tag(release_id, tm, tag, annotated_name)
            else:
                if options['cea_arrangers'] or writer_type == tag:
                    self.append_tag(release_id, tm, tag, name)

            if options['cea_arrangers'] or writer_type == tag:
                if sort_tag:
                    self.append_tag(release_id, tm, sort_tag, sort_name)
                    if options['cea_tag_sort'] and '~' in sort_tag:
                        explicit_sort_tag = sort_tag.replace('~', '')
                        self.append_tag(release_id, tm, explicit_sort_tag, sort_name)

            self.append_tag(release_id, tm, cwp_tag, annotated_name)
            self.append_tag(release_id, tm, cwp_names_tag, name)
            if instrumented_name != name:
                self.append_tag(release_id, tm, cwp_instrumented_tag, instrumented_name)

            if cwp_sort_tag:
                self.append_tag(release_id, tm, cwp_sort_tag, sort_name)

            if caller == 'PartLevels' and (
                    writer_type == 'lyricist' or writer_type == 'librettist'):
                self.lyricist_filled[track] = True
                write_log(release_id, 'info', 'Filled lyricist for track %s. Not looking further',
                              track)

            if writer_type == 'composer':
                if sort_name in self.release_artists_sort[album]:
                    composerlast = sort_name.split(",")[0]
                    self.append_tag(release_id, tm, '~cea_album_composers', name)
                    self.append_tag(release_id, tm, '~cea_album_composers_sort', sort_name)
                    self.append_tag(release_id, tm, '~cea_album_track_composer_lastnames', composerlast)
                    composer_last_names(self, release_id, tm, album)


# Non-Latin character processing
latin_letters = {}


def is_latin(uchr):
    """Test whether character is in Latin script"""
    try:
        return latin_letters[uchr]
    except KeyError:
        return latin_letters.setdefault(
            uchr, 'LATIN' in unicodedata.name(uchr))


def only_roman_chars(unistr):
    """Test whether string is in Latin script"""
    return all(is_latin(uchr)
               for uchr in unistr
               if uchr.isalpha())


def get_roman(string):
    """Transliterate cyrillic script to Latin script"""
    capital_letters = {
        u'А': u'A',
        u'Б': u'B',
        u'В': u'V',
        u'Г': u'G',
        u'Д': u'D',
        u'Е': u'E',
        u'Ё': u'E',
        u'Ж': u'Zh',
        u'З': u'Z',
        u'И': u'I',
        u'Й': u'Y',
        u'К': u'K',
        u'Л': u'L',
        u'М': u'M',
        u'Н': u'N',
        u'О': u'O',
        u'П': u'P',
        u'Р': u'R',
        u'С': u'S',
        u'Т': u'T',
        u'У': u'U',
        u'Ф': u'F',
        u'Х': u'H',
        u'Ц': u'Ts',
        u'Ч': u'Ch',
        u'Ш': u'Sh',
        u'Щ': u'Sch',
        u'Ъ': u'',
        u'Ы': u'Y',
        u'Ь': u'',
        u'Э': u'E',
        u'Ю': u'Yu',
        u'Я': u'Ya'
    }
    lower_case_letters = {
        u'а': u'a',
        u'б': u'b',
        u'в': u'v',
        u'г': u'g',
        u'д': u'd',
        u'е': u'e',
        u'ё': u'e',
        u'ж': u'zh',
        u'з': u'z',
        u'и': u'i',
        u'й': u'y',
        u'к': u'k',
        u'л': u'l',
        u'м': u'm',
        u'н': u'n',
        u'о': u'o',
        u'п': u'p',
        u'р': u'r',
        u'с': u's',
        u'т': u't',
        u'у': u'u',
        u'ф': u'f',
        u'х': u'h',
        u'ц': u'ts',
        u'ч': u'ch',
        u'ш': u'sh',
        u'щ': u'sch',
        u'ъ': u'',
        u'ы': u'y',
        u'ь': u'',
        u'э': u'e',
        u'ю': u'yu',
        u'я': u'ya'
    }
    translit_string = ""
    for index, char in enumerate(string):
        if char in lower_case_letters.keys():
            char = lower_case_letters[char]
        elif char in capital_letters.keys():
            char = capital_letters[char]
            if len(string) > index + 1:
                if string[index + 1] not in lower_case_letters.keys():
                    char = char.upper()
            else:
                char = char.upper()
        translit_string += char
    # fix multi-chars
    translit_string = translit_string.replace('ks', 'x').replace('iy ', 'i ')
    return translit_string


def remove_middle(performer):
    """To remove middle names of Russian composers"""
    plist = performer.split()
    if len(plist) == 3:
        return plist[0] + ' ' + plist[2]
    else:
        return performer


# Sorting etc.


def unsort(performer):
    """
    To take a sort field and recreate the name
    Only now used for last-ditch cyrillic translation - superseded by 'translate_from_sortname'
    """
    sorted_list = performer.split(', ')
    sorted_list.reverse()
    for i, item in enumerate(sorted_list):
        if item[-1] != "'":
            sorted_list[i] += ' '
    return ''.join(sorted_list).strip()


def translate_from_sortname(name, sortname):
    """
    'Translate' the artist name by reversing the sortname.
    Code is from picard/util/__init__.py
    """
    for c in name:
        ctg = unicodedata.category(c)
        if ctg[0] == "L" and unicodedata.name(c).find("LATIN") == -1:
            for separator in (" & ", "; ", " and ", " vs. ", " with ", " y "):
                if separator in sortname:
                    parts = sortname.split(separator)
                    break
            else:
                parts = [sortname]
                separator = ""
            return separator.join(map(_reverse_sortname, parts))
    return name


def _reverse_sortname(sortname):
    """
    Reverse sortnames.
    Code is from picard/util/__init__.py
    """

    chunks = [a.strip() for a in sortname.split(",")]
    chunk_len = len(chunks)
    if chunk_len == 2:
        return "%s %s" % (chunks[1], chunks[0])
    elif chunk_len == 3:
        return "%s %s %s" % (chunks[2], chunks[1], chunks[0])
    elif chunk_len == 4:
        return "%s %s, %s %s" % (chunks[1], chunks[0], chunks[3], chunks[2])
    else:
        return sortname.strip()


def stripsir(performer):
    """Remove honorifics from names"""
    performer = performer.replace(u'\u2010', u'-').replace(u'\u2019', u"'")
    sir = re.compile(r'(.*)\b(Sir|Maestro|Dame)\b\s*(.*)', re.IGNORECASE)
    match = sir.search(performer)
    if match:
        return match.group(1) + match.group(3)
    else:
        return performer


# def swap_prefix(performer):
#     """NOT CURRENTLY USED. Create sort fields for ensembles etc., by placing the prefix (see constants) at the end"""
#     prefix = '|'.join(prefixes)
#     swap = re.compile(r'^(' + prefix + r')\b\s*(.*)', re.IGNORECASE)
#     match = swap.search(performer)
#     if match:
#         return match.group(2) + ", " + match.group(1)
#     else:
#         return performer


def replace_roman_numerals(s):
    """Replaces roman numerals include in s, where followed by punctuation, by digits"""
    p = re.compile(
        r'\b(M{0,4}(CM|CD|D?)?C{0,3}(XC|XL|L?)?X{0,3}(IX|IV|V?)?I{0,3})\b(\.|:|,|;|$)',
        # was
        # r'(^|\s)(\bM{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})\b)(\W|\s|$)',
        re.IGNORECASE | re.UNICODE)  # Matches Roman numerals (+ ensure non-Latin chars treated as word chars)
    romans = p.findall(s)
    for roman in romans:
        if roman[0]:
            numerals = unicode(roman[0])
            digits = unicode(from_roman(numerals))
            to_replace = roman[0] + r'(\.|:|,|;|$)'
            s = re.sub(to_replace, digits, s)
    return s


def from_roman(s):
    romanNumeralMap = (('M', 1000),
                       ('CM', 900),
                       ('D', 500),
                       ('CD', 400),
                       ('C', 100),
                       ('XC', 90),
                       ('L', 50),
                       ('XL', 40),
                       ('X', 10),
                       ('IX', 9),
                       ('V', 5),
                       ('IV', 4),
                       ('I', 1))
    result = 0
    index = 0
    for numeral, integer in romanNumeralMap:
        while s[index:index + len(numeral)] == numeral:
            result += integer
            index += len(numeral)
    return result


def turbo_lcs(release_id, multi_list):
    """
    Picks the best longest common string method to use
    Works with lists or strings
    :param release_id: 
    :param multi_list: a list of strings or a list of lists
    :return: longest common substring/list
    """
    write_log(release_id, 'debug', 'In turbo_lcs')
    if not isinstance(multi_list, list):
        return None
    list_sum = sum([len(x) for x in multi_list])
    list_len = len(multi_list)
    if list_len < 2:
        write_log(release_id, 'debug', 'Only one item in list - no algo required')
        return multi_list[0]  # Nothing to do!
    # for big matches, use the generalised suffix tree method
    if ((list_sum / list_len) ** 2) * list_len > 1000:
        # heuristic: may need to tweak the 1000 in the light of results
        lcs_list = suffixtree.multi_lcs(multi_list)
        if "error" not in lcs_list:
            if "response" in lcs_list:
                    write_log(release_id, 'debug', 'LCS returned from suffix tree algo')
                    return lcs_list['response']
            else:
                write_log(release_id, 'error',
                          'Suffix tree failure for release %s. Error unknown. Using standard lcs algo instead',
                          release_id)
        else:
            write_log(release_id, 'debug',
                      'Suffix tree failure for release %s. Error message: %s. Using standard lcs algo instead',
                      release_id, lcs_list['error'])
    # otherwise, or if gst fails, use the standard algorithm
    first = True
    common = []
    for item in multi_list:
        if first:
            common = item
            first = False
        else:
            lcs = longest_common_substring(
                item, common)
            common = lcs['string']
    write_log(release_id, 'debug', 'LCS returned from standard algo')
    return common


def longest_common_substring(s1, s2):
    """
    Standard lcs algo for short strings, or if suffix tree does not work
    :param s1: substring 1
    :param s2: substring 2
    :return: {'string': the longest common substring,
        'start': the start position in s1,
        'length': the length of the common substring}
    NB this also works on list arguments - i.e. it will find the longest common sub-list
    """
    m = [[0] * (1 + len(s2)) for i in xrange(1 + len(s1))]
    longest, x_longest = 0, 0
    for x in xrange(1, 1 + len(s1)):
        for y in xrange(1, 1 + len(s2)):
            if s1[x - 1] == s2[y - 1]:
                m[x][y] = m[x - 1][y - 1] + 1
                if m[x][y] > longest:
                    longest = m[x][y]
                    x_longest = x
            else:
                m[x][y] = 0
    return {'string': s1[x_longest - longest: x_longest],
            'start': x_longest - longest, 'length': x_longest}


def longest_common_sequence(list1, list2, minstart=0, maxstart=0):
    """
    :param list1: list 1
    :param list2: list 2
    :param minstart: the earliest point to start looking for a match
    :param maxstart: the latest point to start looking for a match
    :return: {'sequence': the common subsequence, 'length': length of subsequence}
    maxstart must be >= minstart. If they are equal then the start point is fixed.
    Note that this only finds subsequences starting at the same position
    Use longest_common_substring for the more general problem
    """
    if maxstart < minstart:
        return None, 0
    min_len = min(len(list1), len(list2))
    longest = 0
    seq = None
    maxstart = min(maxstart, min_len) + 1
    for k in range(minstart, maxstart):
        for i in range(k, min_len + 1):
            if list1[k:i] == list2[k:i] and i - k > longest:
                longest = i - k
                seq = list1[k:i]
    return {'sequence': seq, 'length': longest}


def substart_finder(mylist, pattern):
    for i in range(len(mylist)):
        if mylist[i] == pattern[0] and mylist[i:i+len(pattern)] == pattern:
            return i
    return len(mylist)  # if nothing found


def map_tags(options, release_id, album, tm):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param options: options passed from either Artists or Workparts
    :param album:
    :param tm: track metadata
    :return: None - action is through setting tm contents
    This is a common function for Artists and Workparts which should only run after both sections have completed for
    a given track. If, say, Artists calls it and Workparts is not done,
    then it will not execute until Workparts calls it (and vice versa).
    """
    ERROR = options["log_error"]
    WARNING = options["log_warning"]
    DEBUG = options["log_debug"]
    INFO = options["log_info"]
    if DEBUG or INFO:
        write_log(release_id, 'debug', 'In map_tags, checking readiness...')
    if (options['classical_extra_artists'] and '~cea_artists_complete' not in tm) or (
            options['classical_work_parts'] and '~cea_works_complete' not in tm):
        if INFO:
            write_log(release_id, 'info', '...not ready')
        return
    if DEBUG or INFO:
        write_log(release_id, 'debug', '... processing tag mapping')
    if INFO:
        for ind, opt in enumerate(options):
            write_log(release_id, 'info', 'Option %s of %s. Option= %s, Value= %s', ind + 1, len(options), opt,
                      options[opt])
    # album
    if tm['~cea_album_composer_lastnames']:
        if isinstance(tm['~cea_album_composer_lastnames'], list):
            last_names = tm['~cea_album_composer_lastnames']
        else:
            last_names = tm['~cea_album_composer_lastnames'].split(';')
        if options['cea_composer_album']:
            # save it as a list to prevent splitting when appending tag
            tm['~cea_release'] = [tm['album']]
            new_last_names = []
            for last_name in last_names:
                last_name = last_name.strip()
                new_last_names.append(last_name)
            if len(new_last_names) > 0:
                tm['album'] = "; ".join(new_last_names) + ": " + tm['album']

    # lyricists
    if options['cea_no_lyricists'] and 'vocals' not in tm['~cea_performers']:
        if 'lyricist' in tm:
            del tm['lyricist']
    for lyricist_tag in ['lyricists', 'librettists', 'translators']:
        if '~cwp_' + lyricist_tag in tm:
            del tm['~cwp_' + lyricist_tag]

    # genres
    if config.setting['folksonomy_tags'] and 'genre' in tm:
        candidate_genres = str_to_list(tm['genre'])
        append_tag(release_id, tm, '~cea_candidate_genres', candidate_genres)
        del tm['genre']  # to avoid confusion as it will contain unmatched folksonomy tags
    else:
        candidate_genres = []
    is_classical = False
    composers_not_found = []
    composer_found = False
    composer_born_list = []
    composer_died_list = []
    arrangers_not_found = []
    arranger_found = False
    arranger_born_list = []
    arranger_died_list = []
    if options['cwp_use_muso_refdb'] and options['cwp_muso_classical'] or options['cwp_muso_dates']:
        if COMPOSER_DICT:
            composer_list = str_to_list(tm['~cwp_composer_names'])
            lc_composer_list = [c.lower() for c in composer_list]
            for composer in lc_composer_list:
                for classical_composer in COMPOSER_DICT:
                    if composer in classical_composer['lc_name']:
                        if options['cwp_muso_classical']:
                            candidate_genres.append('Classical')
                            is_classical = True
                        if options['cwp_muso_dates']:
                            composer_born_list = classical_composer['birth']
                            composer_died_list = classical_composer['death']
                        composer_found = True
                        break
                if not composer_found:
                    composer_index = lc_composer_list.index(composer)
                    orig_composer = composer_list[composer_index]
                    composers_not_found.append(orig_composer)
                    append_tag(release_id, tm, '~cwp_unrostered_composers', orig_composer)
            if composers_not_found:
                append_tag(release_id, tm, '003_information:composers', 'Composer(s) '
                           + list_to_str(
                    composers_not_found) + ' not found in reference database of classical composers')

            # do the same for arrangers, if required
            if options['cwp_genres_arranger_as_composer'] or options['cwp_periods_arranger_as_composer']:
                arranger_list = str_to_list(tm['~cea_arranger_names']) + str_to_list(tm['~cwp_arranger_names'])
                lc_arranger_list = [c.lower() for c in arranger_list]
                for arranger in lc_arranger_list:
                    for classical_arranger in COMPOSER_DICT:
                        if arranger in classical_arranger['lc_name']:
                            if options['cwp_muso_classical'] and options['cwp_genres_arranger_as_composer']:
                                candidate_genres.append('Classical')
                                is_classical = True
                            if options['cwp_muso_dates'] and options['cwp_periods_arranger_as_composer']:
                                arranger_born_list = classical_arranger['birth']
                                arranger_died_list = classical_arranger['death']
                            arranger_found = True
                            break
                    if not arranger_found:
                        arranger_index = lc_arranger_list.index(arranger)
                        orig_arranger = arranger_list[arranger_index]
                        arrangers_not_found.append(orig_arranger)
                        append_tag(release_id, tm, '~cwp_unrostered_arrangers', orig_arranger)
                if arrangers_not_found:
                    append_tag(release_id, tm, '003_information:arrangers',
                               'Arranger(s) ' + list_to_str(arrangers_not_found) +
                               ' not found in reference database of classical composers')

        else:
            append_tag(release_id, tm, '001_errors:8',
                       '8. No composer reference file. Check log for error messages re path name.')

    if options['cwp_use_muso_refdb'] and options['cwp_muso_genres'] and GENRE_DICT:
        main_classical_genres_list = [list_to_str(mg['name']).strip() for mg in GENRE_DICT]
    else:
        main_classical_genres_list = [sg.strip() for sg in options['cwp_genres_classical_main'].split(',')]
    sub_classical_genres_list = [sg.strip() for sg in options['cwp_genres_classical_sub'].split(',')]
    main_other_genres_list = [sg.strip() for sg in options['cwp_genres_other_main'].split(',')]
    sub_other_genres_list = [sg.strip() for sg in options['cwp_genres_other_sub'].split(',')]
    main_classical_genres = []
    sub_classical_genres = []
    main_other_genres = []
    sub_other_genres = []
    if '~cea_work_type' in tm:
        candidate_genres += str_to_list(tm['~cea_work_type'])
    if '~cwp_candidate_genres' in tm:
        candidate_genres += str_to_list(tm['~cwp_candidate_genres'])
    if INFO:
        write_log(release_id, 'info', "Candidate genres: %r", candidate_genres)
    untagged_genres = []
    if candidate_genres:
        main_classical_genres = [val for val in main_classical_genres_list
                                 if val.lower() in [genre.lower() for genre in candidate_genres]]
        sub_classical_genres = [val for val in sub_classical_genres_list
                                 if val.lower() in [genre.lower() for genre in candidate_genres]]

        if main_classical_genres or sub_classical_genres or options['cwp_genres_classical_all']:
            is_classical = True
            main_classical_genres.append('Classical')
            candidate_genres += str_to_list(tm['~cea_work_type_if_classical'])
            # next two are repeated statements, but a separate fn would be clumsy too!
            main_classical_genres = [val for val in main_classical_genres_list
                                     if val.lower() in [genre.lower() for genre in candidate_genres]]
            sub_classical_genres = [val for val in sub_classical_genres_list
                                    if val.lower() in [genre.lower() for genre in candidate_genres]]
        if options['cwp_genres_classical_exclude']:
            main_classical_genres = [g for g in main_classical_genres if g.lower() != 'classical']

        main_other_genres = [val for val in main_other_genres_list
                                 if val.lower() in [genre.lower() for genre in candidate_genres]]
        sub_other_genres = [val for val in sub_other_genres_list
                                 if val.lower() in [genre.lower() for genre in candidate_genres]]
        all_genres = main_classical_genres + sub_classical_genres + main_other_genres + sub_other_genres
        untagged_genres = [un for un in candidate_genres
                           if un.lower() not in [genre.lower() for genre in all_genres]]


    if options['cwp_genre_tag']:
        append_tag(release_id, tm, options['cwp_genre_tag'], main_classical_genres + main_other_genres)
    if options['cwp_subgenre_tag']:
        append_tag(release_id, tm, options['cwp_subgenre_tag'], sub_classical_genres + sub_other_genres)
    if is_classical and options['cwp_genres_flag_text'] and options['cwp_genres_flag_tag']:
        tm[options['cwp_genres_flag_tag']] = options['cwp_genres_flag_text']
    if not (main_classical_genres + main_other_genres):
        if options['cwp_genres_default']:
            append_tag(release_id, tm, options['cwp_genre_tag'], options['cwp_genres_default'])
        else:
            if options['cwp_genre_tag'] in tm:
                del tm[options['cwp_genre_tag']]
    if untagged_genres:
        append_tag(release_id, tm, '003_information:genres',
                   'Candidate genres found but not matched: ' + list_to_str(untagged_genres))
        append_tag(release_id, tm, '~cwp_untagged_genres', untagged_genres)

    # instruments and keys
    if options['cwp_instruments_MB_names'] and options['cwp_instruments_credited_names'] and tm['~cea_instruments_all']:
        instruments = tm['~cea_instruments_all']
    elif options['cwp_instruments_MB_names'] and tm['~cea_instruments']:
        instruments = tm['~cea_instruments']
    elif options['cwp_instruments_credited_names'] and tm['~cea_instruments_credited']:
        instruments = tm['~cea_instruments_credited']
    else:
        instruments = None
    if instruments and options['cwp_instruments_tag']:
        append_tag(release_id, tm, options['cwp_instruments_tag'], instruments)
        # need to append rather than over-write as it may be the same as another tag (e.g. genre)
    if tm['~cwp_keys'] and options['cwp_key_tag']:
        append_tag(release_id, tm, options['cwp_key_tag'], tm['~cwp_keys'])

    # dates
    if options['cwp_workdate_annotate']:
        comp = ' (composed)'
        publ = ' (published)'
        prem = ' (premiered)'
    else:
        comp = ''
        publ = ''
        prem = ''
    tm[options['cwp_workdate_tag']] = ''
    earliest_date = 9999
    latest_date = -9999
    found = False
    if tm['~cwp_composed_dates']:
        composed_dates_list = str_to_list(tm['~cwp_composed_dates'])
        if len(composed_dates_list) > 1:
            composed_dates_list = str_to_list(composed_dates_list[0])  # use dates of lowest-level work
        earliest_date = min([int(dates.split(DATE_SEP)[0].strip()) for dates in composed_dates_list])
        append_tag(release_id, tm, options['cwp_workdate_tag'], list_to_str(composed_dates_list) + comp)
        found = True
    if tm['~cwp_published_dates'] and (not found or options['cwp_workdate_use_all']):
        if not found:
            published_dates_list = str_to_list(tm['~cwp_published_dates'])
            if len(published_dates_list) > 1:
                published_dates_list = str_to_list(published_dates_list[0])  # use dates of lowest-level work
            earliest_date = min([int(dates.split(DATE_SEP)[0].strip()) for dates in published_dates_list])
            append_tag(release_id, tm, options['cwp_workdate_tag'], list_to_str(published_dates_list) + publ)
            found = True
    if tm['~cwp_premiered_dates'] and (not found or options['cwp_workdate_use_all']):
        if not found:
            premiered_dates_list = str_to_list(tm['~cwp_premiered_dates'])
            if len(premiered_dates_list) > 1:
                premiered_dates_list = str_to_list(premiered_dates_list[0])  # use dates of lowest-level work
            earliest_date = min([int(dates.split(DATE_SEP)[0].strip()) for dates in premiered_dates_list])
            append_tag(release_id, tm, options['cwp_workdate_tag'], list_to_str(premiered_dates_list) + prem)

    # periods
    PERIODS = {}
    if options['cwp_period_map']:
        if options['cwp_use_muso_refdb'] and options['cwp_muso_periods'] and PERIOD_DICT:
            for p_item in PERIOD_DICT:
                if 'start' not in p_item or p_item['start'] == []:
                    p_item['start'] = [u'-9999']
                if 'end' not in p_item or p_item['end'] == []:
                    p_item['end'] = [u'2525']
                if 'name' not in p_item or p_item['name'] == []:
                    p_item['name'] = ['NOT SPECIFIED']
            PERIODS = {list_to_str(mp['name']).strip(): (
                list_to_str(mp['start']),
                list_to_str(mp['end']))
                for mp in PERIOD_DICT}
            for period in PERIODS:
                if PERIODS[period][0].lstrip('-').isdigit() and PERIODS[period][1].lstrip('-').isdigit():
                    PERIODS[period] = (int(PERIODS[period][0]), int(PERIODS[period][1]))
                else:
                    PERIODS[period] = 'ERROR - start and/or end of ' + period + ' are not integers'

        else:
            periods = [p.strip() for p in options['cwp_period_map'].split(';')]
            for p in periods:
                p = p.split(',')
                if len(p) == 3:
                    period = p[0].strip()
                    start = p[1].strip()
                    end = p[2].strip()
                    if start.lstrip('-').isdigit() and end.lstrip('-').isdigit():
                        PERIODS[period] = (int(start), int(end))
                    else:
                        PERIODS[period] = 'ERROR - start and/or end of ' + period + ' are not integers'
                else:
                    PERIODS[p[0]] = 'ERROR in period map - each item must contain 3 elements'
    if options['cwp_period_tag'] and PERIODS:
        if earliest_date == 9999:  # i.e. no work date found
            if options['cwp_use_muso_refdb'] and options['cwp_muso_dates']:
                for composer_born in composer_born_list + arranger_born_list:
                    if composer_born and composer_born.isdigit():
                        birthdate = int(composer_born)
                        earliest_date = min(earliest_date, birthdate + 20)  # productive age is taken as 20->death as per Muso
                        for composer_died in composer_died_list + arranger_died_list:
                            if composer_died and composer_died.isdigit():
                                deathdate = int(composer_died)
                                latest_date = max(latest_date, deathdate)
                            else:
                                latest_date = datetime.now().year
        for period in PERIODS:
            if 'ERROR' in PERIODS[period]:
                tm[options['cwp_period_tag']] = ''
                append_tag(release_id, tm, '001_errors:9', '9. ' + PERIODS[period])
                break
            if earliest_date < 9999:
                if PERIODS[period][0] <= earliest_date <= PERIODS[period][1]:
                    append_tag(release_id, tm, options['cwp_period_tag'], period)
            if latest_date > -9999:
                if PERIODS[period][0] <= latest_date <= PERIODS[period][1]:
                    append_tag(release_id, tm, options['cwp_period_tag'], period)

    # generic tag mapping
    sort_tags = options['cea_tag_sort']
    if sort_tags:
        tm['artists_sort'] = tm['~artists_sort']
    for i in range(0, 16):
        tagline = options['cea_tag_' + unicode(i + 1)].split(",")
        source_group = options['cea_source_' + unicode(i + 1)].split(",")
        conditional = options['cea_cond_' + unicode(i + 1)]
        for item, tagx in enumerate(tagline):
            tag = tagx.strip()
            sort = sort_suffix(tag)
            if not conditional or tm[tag] == "":
                for source_memberx in source_group:
                    source_member = source_memberx.strip()
                    sourceline = source_member.split("+")
                    if len(sourceline) > 1:
                        source = "\\"
                        for source_itemx in sourceline:
                            source_item = source_itemx.strip()
                            source_itema = source_itemx.lstrip()
                            if INFO:
                                write_log(release_id, 'info', "Source_item: %s", source_item)
                            if "~cea_" + source_item in tm:
                                si = tm['~cea_' + source_item]
                            elif "~cwp_" + source_item in tm:
                                si = tm['~cwp_' + source_item]
                            elif source_item in tm:
                                si = tm[source_item]
                            elif len(source_itema) > 0 and source_itema[0] == "\\":
                                si = source_itema[1:]
                            else:
                                si = ""
                            if si != "" and source != "":
                                source = source + si
                            else:
                                source = ""
                    else:
                        source = sourceline[0]
                    no_names_source = re.sub('(_names)$', 's', source)
                    source_sort = sort_suffix(source)
                    if INFO:
                        write_log(release_id, 'info',
                                  "Tag mapping: Line: %s, Source: %s, Tag: %s, no_names_source: %s, sort: %s, item %s",
                                  i + 1, source, tag, no_names_source, sort, item)
                    if '~cea_' + source in tm or '~cwp_' + source in tm:
                        for prefix in ['~cea_', '~cwp_']:
                            if prefix + source in tm:
                                if INFO:
                                    write_log(release_id, 'info', prefix)
                                append_tag(release_id, tm, tag, tm[prefix + source], ['; '])
                                if sort_tags:
                                    if prefix + no_names_source + source_sort in tm:
                                        if INFO:
                                            write_log(release_id, 'info', prefix + " sort")
                                        append_tag(release_id, tm, tag + sort,
                                                   tm[prefix + no_names_source + source_sort], ['; '])
                    elif source in tm or '~' + source in tm:
                        if INFO:
                            write_log(release_id, 'info', "Picard")
                        for p in ['', '~']:
                            if p + source in tm:
                                append_tag(release_id, tm, tag, tm[p + source], ['; ', '/ '])
                        if sort_tags:
                            if "~" + source + source_sort in tm:
                                source = "~" + source
                            if source + source_sort in tm:
                                if INFO:
                                    write_log(release_id, 'info', "Picard sort")
                                append_tag(release_id, tm, tag + sort, tm[source + source_sort], ['; ', '/ '])
                    elif len(source) > 0 and source[0] == "\\":
                        append_tag(release_id, tm, tag, source[1:], ['; ', '/ '])
                    else:
                        pass
    if ERROR and "~cea_error" in tm:
        for error in str_to_list(tm['~cea_error']):
            ecode = error[0]
            append_tag(release_id, tm, '001_errors:' + ecode, error)
    if WARNING and "~cea_warning" in tm:
        for warning in str_to_list(tm['~cea_warning']):
            wcode = warning[0]
        append_tag(release_id, tm, '002_warnings:' + wcode, warning)
    if not DEBUG:
        if '~cea_works_complete' in tm:
            del tm['~cea_works_complete']
        if '~cea_artists_complete' in tm:
            del tm['~cea_artists_complete']
        del_list = []
        for t in tm:
            if 'ce_tag_cleared' in t:
                del_list.append(t)
        for t in del_list:
            del tm[t]
    # if options over-write enabled, remove it after processing one album
    options['ce_options_overwrite'] = False
    config.setting['ce_options_overwrite'] = False
    # so that options are not retained (in case of refresh with different
    # options)
    if '~ce_options' in tm:
        del tm['~ce_options']
    # remove any unwanted file tags
    if '~ce_file' in tm and tm['~ce_file'] != "None":
        music_file = tm['~ce_file']
        orig_metadata = album.tagger.files[music_file].orig_metadata
        if 'delete_tags' in options and options['delete_tags']:
            warn = []
            for delete_item in options['delete_tags']:
                if delete_item not in tm:  # keep the original for comparison if we have a new version
                    if delete_item in orig_metadata:
                        del orig_metadata[delete_item]
                        warn.append(delete_item)
            if warn and WARNING:
                append_tag(release_id, tm, '002_warnings:7', '7. Deleted tags: ' + ', '.join(warn))
                write_log(release_id, 'warning', 'Deleted tags: ' + ', '.join(warn))

def sort_suffix(tag):
    """To determine what sort suffix is appropriate for a given tag"""
    if tag == "composer" or tag == "artist" or tag == "albumartist" or tag == "trackartist" or tag == "~cea_MB_artist":
        sort = "sort"
    else:
        sort = "_sort"
    return sort


def append_tag(release_id, tm, tag, source, separators=None):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param tm: track metadata
    :param tag: tag to be appended to
    :param source: item to append to tag
    :param separators: characters which may be used to split string into a list
        (any of the characters will be a split point)
    :return: None. Action is on tm
    """
    if not separators:
        separators = []
    if tag:
        if config.setting['log_info']:
            write_log(release_id, 'info', 'Appending source: %r to tag: %s (source is type %s) ...',
                      source, tag, type(source))
            write_log(release_id, 'info', '... existing tag contents = %r', tm[tag])
        if source and len(source) > 0:
            if isinstance(source, basestring):
                source = source.replace(u'\u2010', u'-')
                source = source.replace(u'\u2019', u"'")
                source = source.replace(u'\u2018', u"'")
                source = source.replace(u'\u201c', u'"')
                source = source.replace(u'\u201d', u'"')
                source = re.split('|'.join(separators), source)

            if tag in tm:
                for source_item in source:
                    if isinstance(source_item, basestring):
                        source_item = source_item.replace(u'\u2010', u'-')
                        source_item = source_item.replace(u'\u2019', u"'")
                        source_item = source_item.replace(u'\u2018', u"'")
                        source_item = source_item.replace(u'\u201c', u'"')
                        source_item = source_item.replace(u'\u201d', u'"')
                    if source_item not in tm[tag]:
                        if not isinstance(tm[tag], list):
                            tag_list = re.split('|'.join(separators), tm[tag])
                            tag_list.append(source_item)
                            tm[tag] = tag_list
                            # Picard will have converted it from list to string
                        else:
                            tm[tag].append(source_item)
            else:
                if tag and tag != "":
                    if isinstance(source, list):
                        if tag == 'artists_sort':
                            # no artists_sort tag in Picard - just a hidden var
                            hidden = tm['~artists_sort']
                            if not isinstance(hidden, list):
                                hidden = re.split('|'.join(separators), hidden)
                            source = add_list_uniquely(source, hidden)
                        for source_item in source:
                            if isinstance(source_item, basestring):
                                source_item = source_item.replace(
                                    u'\u2010', u'-')
                                source_item = source_item.replace(
                                    u'\u2019', u"'")

                            if tag not in tm:
                                tm[tag] = [source_item]
                            else:
                                if not isinstance(tm[tag], list):
                                    tag_list = re.split(
                                        '|'.join(separators), tm[tag])
                                    tag_list.append(source_item)
                                    tm[tag] = tag_list
                                else:
                                    tm[tag].append(source_item)
                    else:
                        tm[tag] = [source]
                        # probably makes no difference to specify a list as Picard will convert the tag to string,
                        # but do it anyway



def get_artist_credit(options, release_id, obj):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param options:
    :param obj: an XmlNode
    :return: a list of as-credited names
    """
    name_credit_list = parse_data(release_id, obj, [], 'artist_credit', 'name_credit')
    credit_list = []
    if name_credit_list:
        for name_credits in name_credit_list:
            for name_credit in name_credits:
                credited_artist = parse_data(release_id, name_credit, [], 'name', 'text')
                if credited_artist:
                    name = parse_data(release_id, name_credit, [], 'artist', 'name', 'text')
                    sort_name = parse_data(release_id, name_credit, [], 'artist', 'sort_name', 'text')
                    credit_item = (credited_artist, name, sort_name)
                    credit_list.append(credit_item)
        return credit_list


def get_aliases_and_credits(self, options, release_id, album, obj, lang, credited):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param album:
    :param self: This relates to the object in the class which called this function
    :param options:
    :param obj: an XmlNode
    :param lang: The language selected in the Picard metadata options
    :param credited: The options item to determine what as-credited names are being sought
    :return: None. Sets self.artist_aliases and self.artist_credits[album]
    """
    name_credit_list = parse_data(release_id, obj, [], 'artist_credit', 'name_credit')
    artist_list = parse_data(release_id, name_credit_list, [], 'artist')
    for artist in artist_list:
        sort_names = parse_data(release_id, artist, [], 'sort_name', 'text')
        if sort_names:
            aliases = parse_data(release_id, artist, [], 'alias_list', 'alias', 'attribs.locale:' +
                                 lang, 'attribs.primary:primary', 'text')
            if aliases:
                self.artist_aliases[sort_names[0]] = aliases[0]
    if credited:
        for name_credits in name_credit_list:
            for name_credit in name_credits:
                credited_artists = parse_data(release_id, name_credit, [], 'name', 'text')
                if credited_artists:
                    sort_names = parse_data(release_id, name_credit, [], 'artist', 'sort_name', 'text')
                    if sort_names:
                        self.artist_credits[album][sort_names[0]
                                                   ] = credited_artists[0]


def get_relation_credits(self, options, release_id, album, obj):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param self:
    :param options: UI options
    :param album: current album
    :param obj: XmloOde
    :return: None
    Note that direct recording relationships will over-ride indirect ones (via work)
    """
    rels = parse_data(release_id, obj, [], 'relation_list', 'attribs.target_type:work', 'relation',
                      'attribs.type:performance', 'work', 'relation_list', 'attribs.target_type:artist', 'relation')
    for rel in rels:
        for artist in rel:
            sort_names = parse_data(release_id, artist, [], 'artist', 'sort_name', 'text')
            if sort_names:
                credited_artists = parse_data(release_id, artist, [], 'target_credit', 'text')
                if credited_artists:
                    self.artist_credits[album][sort_names[0]
                                               ] = credited_artists[0]
    rels2 = parse_data(release_id, obj, [], 'relation_list', 'attribs.target_type:artist', 'relation')
    for rel in rels2:
        for artist in rel:
            sort_names = parse_data(release_id, artist, [], 'artist', 'sort_name', 'text')
            if sort_names:
                credited_artists = parse_data(release_id, artist, [], 'target_credit', 'text')
                if credited_artists:
                    self.artist_credits[album][sort_names[0]
                                               ] = credited_artists[0]


def composer_last_names(self, release_id, tm, album):
    """
    :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
    :param self:
    :param tm:
    :param album:
    :return: None
    Sets composer last names for album prefixing
    """
    if '~cea_album_track_composer_lastnames' in tm:
        if not isinstance(tm['~cea_album_track_composer_lastnames'], list):
            atc_list = re.split(
                '|'.join(
                    self.SEPARATORS),
                tm['~cea_album_track_composer_lastnames'])
        else:
            atc_list = tm['~cea_album_track_composer_lastnames']
        for atc_item in atc_list:
            composer_lastnames = atc_item.strip()
            if '~length' in tm and tm['~length']:
                track_length = time_to_secs(tm['~length'])
            else:
                track_length = 0
            if album in self.album_artists:
                if 'composer_lastnames' in self.album_artists[album]:
                    if composer_lastnames not in self.album_artists[album]['composer_lastnames']:
                        self.album_artists[album]['composer_lastnames'][composer_lastnames] = {
                            'length': track_length}
                    else:
                        self.album_artists[album]['composer_lastnames'][composer_lastnames]['length'] += track_length
                else:
                    self.album_artists[album]['composer_lastnames'][composer_lastnames] = {
                        'length': track_length}
            else:
                self.album_artists[album]['composer_lastnames'][composer_lastnames] = {
                    'length': track_length}
    else:
        if self.WARNING or self.INFO:
            write_log(release_id, 'warning',
                      "No _cea_album_track_composer_lastnames variable available for recording \"%s\".", tm['title'])
        if 'composer' in tm:
            self.append_tag(release_id, release_id, tm, '~cea_warning',
                            '1. Composer for this track is not in album artists and will not be available to prefix album')
        else:
            self.append_tag(release_id, release_id, tm, '~cea_warning',
                            '1. No composer for this track, but checking parent work.')


def add_list_uniquely(list_to, list_from):
    """
    Adds any items in list_from to list_to, if they are not already present
    If either arg is a string, it will be converted to a list, e.g. 'abc' -> ['abc']
    :param list_to:
    :param list_from:
    :return: appends only unique elements of list 2 to list 1
    """
    #
    if list_to and list_from:
        if not isinstance(list_to, list):
            list_to = str_to_list(list_to)
        if not isinstance(list_from, list):
            list_from = str_to_list(list_from)
        for list_item in list_from:
            if list_item not in list_to:
                list_to.append(list_item)
    else:
        if list_from:
            list_to = list_from
    return list_to


def str_to_list(s):
    """
    :param s:
    :return: list from string using ; as separator
    """
    if not isinstance(s, basestring):
        try:
            return list(s)
        except TypeError:
            return []
    else:
        if s == '':
            return []
        else:
            return s.split('; ')

def list_to_str(l):
    """
    :param l:
    :return: string from list using ; as separator
    """
    if not isinstance(l, list):
        return l
    else:
        return '; '.join(l)

def interpret(tag):
    """
    :param tag:
    :return: safe form of eval(tag)
    """
    if isinstance(tag, basestring):
        try:
            tag = tag.strip(' \n\t')
            return eval(tag)
        except SyntaxError:
            return tag
    else:
        return tag


def time_to_secs(a):
    """
    :param a: string x:x:x
    :return: seconds
    converts string times to seconds
    """
    ax = a.split(':')
    ax = ax[::-1]
    t = 0
    for i, x in enumerate(ax):
        if x.isdigit():
            t += int(x) * (60 ** i)
        else:
            return 0
    return t


def seq_last_names(self, album):
    """
    Sequences composer last names for album prefix by the total lengths of their tracks
    :param self:
    :param album:
    :return:
    """
    ln = []
    if album in self.album_artists and 'composer_lastnames' in self.album_artists[album]:
        for x in self.album_artists[album]['composer_lastnames']:
            if 'length' in self.album_artists[album]['composer_lastnames'][x]:
                ln.append([x, self.album_artists[album]
                           ['composer_lastnames'][x]['length']])
            else:
                return []
        ln = sorted(ln, key=lambda a: a[1])
        ln = ln[::-1]
    return [a[0] for a in ln]

def year(date):
    """
    Return YYYY portion of date(s) in YYYY-MM-DD format (may be incomplete, string or list)
    :param date:
    :return: YYYY
    """
    if isinstance(date, list):
        year_list = [d.split('-')[0] for d in date]
        return year_list
    else:
        date_list = date.split('-')
        return date_list[0]

#################
#################
# EXTRA ARTISTS #
#################
#################


class ExtraArtists():

    # CONSTANTS
    def __init__(self):
        self.album_artists = collections.defaultdict(
            lambda: collections.defaultdict(dict))
        # collection of artists to be applied at album level
        self.track_listing = collections.defaultdict(list)
        # collection of tracks - format is {album: [track 1,
        # track 2, ...]}
        self.options = collections.defaultdict(dict)
        # collection of Classical Extras options
        self.globals = collections.defaultdict(dict)
        # collection of global variables for this class
        self.album_performers = collections.defaultdict(
            lambda: collections.defaultdict(dict))
        # collection of performers who have release relationships, not track
        # relationships
        self.album_instruments = collections.defaultdict(
            lambda: collections.defaultdict(dict))
        # collection of instruments which have release relationships, not track
        # relationships
        self.artist_aliases = {}
        # collection of alias names - format is {sort_name: alias_name, ...}
        self.artist_credits = collections.defaultdict(dict)
        # collection of credited-as names - format is {album: {sort_name: credit_name,
        # ...}, ...}
        self.release_artists_sort = collections.defaultdict(list)
        # collection of release artists - format is {album: [sort_name_1,
        # sort_name_2, ...]}
        self.lyricist_filled = collections.defaultdict(dict)
        # Boolean for each track to indicate if lyricist has been found (don't
        # want to add more from higher levels)
        # NB this last one is for completeness - not actually used by ExtraArtists, but here to remove pep8 error

    def add_artist_info(
            self,
            album,
            track_metadata,
            trackXmlNode,
            releaseXmlNode):
        """
        Main routine run for each track of release
        :param album: Current release
        :param track_metadata: track metadata dictionary
        :param trackXmlNode: Everything in the track node downwards
        :param releaseXmlNode: Everything in the release node downwards (so includes all track nodes)
        :return:
        """
        release_id = track_metadata['musicbrainz_albumid']
        if 'start' not in release_status[release_id]:
            release_status[release_id]['start'] = datetime.now()
        if 'lookups' not in release_status[release_id]:
            release_status[release_id]['lookups'] = 0
        release_status[release_id]['name'] = track_metadata['album']
        release_status[release_id]['artists'] = True
        write_log(release_id, 'debug', 'STARTING ARTIST PROCESSING FOR ALBUM %s, TRACK %s',
                  track_metadata['album'], track_metadata['tracknumber'] + ' ' + track_metadata['title'])
        # write_log('info', 'trackXmlNode = %s', trackXmlNode) # NB can crash Picard
        # write_log('info', 'releaseXmlNode = %s', releaseXmlNode) # NB can crash Picard
        # Jump through hoops to get track object!!
        track = album._new_tracks[-1]
        tm = track.metadata

        # OPTIONS - OVER-RIDE IF REQUIRED
        if '~ce_options' not in tm:
            write_log(release_id, 'debug', 'Artists gets track first...')
            get_options(release_id, album, track)
        options = interpret(tm['~ce_options'])
        if not options:
            if config.setting["log_error"]:
                write_log(release_id, 'error', 'Artists. Failure to read saved options for track %s. options = %s',
                          track, tm['~ce_options'])
            options = option_settings(config.setting)
        self.options[track] = options

        # CONSTANTS
        self.ERROR = options["log_error"]
        self.WARNING = options["log_warning"]
        self.DEBUG = options["log_debug"]
        self.INFO = options["log_info"]
        self.ORCHESTRAS = options["cea_orchestras"].split(',')
        self.CHOIRS = options["cea_choirs"].split(',')
        self.GROUPS = options["cea_groups"].split(',')
        self.ENSEMBLE_TYPES = self.ORCHESTRAS + self.CHOIRS + self.GROUPS
        self.SEPARATORS = ['; ', '/ ', ';', '/']

        # continue?
        if not options["classical_extra_artists"]:
            return
        # NOT USED
        album_files = album.tagger.get_files_from_objects([album])
        if options['log_info']:
            write_log(release_id, 'info', 'ALBUM FILENAMES for album %r = %s', album, album_files)
        track_files = track.iterfiles(Track(track, album))
        # tf = uniqify(chain(*[track.iterfiles(Track(t, album))for t in [track]]))
        # tf = Tagger.get_files_from_objects(Track(track, album), [track])
        # tf = uniqify(chain(*[t.iterfiles(album) for t in [track]]))
        # tf = track.tagger.get_files_from_objects([track])
        # write_log('error', 'TRACK FILENAMES for track %r = %s', track, track_files)
        # write_log('error', 'TRACK FILENAMES 2 for track %r = %s', track, tf)
        if not (
            options["ce_no_run"] and (
                not tm['~ce_file'] or tm['~ce_file'] == "None")):
            # continue
            if self.DEBUG or self.INFO:
                write_log(release_id, 'debug', "ExtraArtists - add_artist_info")
            if album not in self.track_listing or track not in self.track_listing[album]:
                self.track_listing[album].append(track)
            # fix odd hyphens in names for consistency
            field_types = ['~albumartists', '~albumartists_sort']
            for field_type in field_types:
                if field_type in tm:
                    field = tm[field_type]
                    if isinstance(field, list):
                        for x, it in enumerate(field):
                            field[x] = it.replace(u'\u2010', u'-')
                    elif isinstance(field, basestring):
                        field = field.replace(u'\u2010', u'-')
                    else:
                        pass
                    tm[field_type] = field

            # first time for this album (reloads each refresh)
            if tm['discnumber'] == '1' and tm['tracknumber'] == '1':
                # get artist aliases - these are cached so can be re-used across
                # releases, but are reloaded with each refresh
                get_aliases(self, release_id, album, options, releaseXmlNode)

                # xml_type = 'release'
                # get performers etc who are related at the release level
                relation_list = parse_data(release_id, releaseXmlNode, [], 'relation_list')
                album_performerList = get_artists(options, release_id, tm, relation_list, 'release')['artists']
                self.album_performers[album] = album_performerList
                album_instrumentList = get_artists(options, release_id, tm, relation_list, 'release')['instruments']
                self.album_instruments[album] = album_instrumentList

            else:
                if album in self.album_performers:
                    album_performerList = self.album_performers[album]
                else:
                    album_performerList = []
                if album in self.album_instruments and self.album_instruments[album]:
                    tm['~cea_instruments'] = self.album_instruments[album][0]
                    tm['~cea_instruments_credited'] = self.album_instruments[album][1]
                    tm['~cea_instruments_all'] = self.album_instruments[album][2]
                    # Should be OK to initialise these here as recording artists
                    # yet to be processed

            track_artist_list = parse_data(release_id, trackXmlNode, [], 'artist_credit', 'name_credit')
            if track_artist_list:
                track_artist = []
                track_artistsort = []
                track_artists = []
                track_artists_sort = []
                locale = config.setting["artist_locale"]
                # NB this is the Picard code in /util
                lang = locale.split("_")[0]

                # Set naming option
                # Put naming style into preferential list

                # naming as for vanilla Picard for track artists

                if options['translate_artist_names'] and lang:
                    name_style = ['alias', 'sort']
                    # documentation indicates that processing should be as below,
                    # but processing above appears to reflect what vanilla Picard actually does
                    # if options['standardize_artists']:
                    #     name_style = ['alias', 'sort']
                    # else:
                    #     name_style = ['alias', 'credit', 'sort']
                else:
                    if not options['standardize_artists']:
                        name_style = ['credit']
                    else:
                        name_style = []
                if self.INFO:
                    write_log(release_id, 'info', 'Priority order of naming style for track artists = %s', name_style)
                styled_artists = apply_artist_style(options, release_id, lang, track_artist_list, name_style,
                                                    track_artist, track_artistsort, track_artists, track_artists_sort)
                tm['artists'] = styled_artists['artists']
                tm['~artists_sort'] = styled_artists['artists_sort']
                tm['artist'] = styled_artists['artist']
                tm['artistsort'] = styled_artists['artistsort']

            if 'recording' in trackXmlNode.children:
                self.globals[track]['is_recording'] = True
                for record in trackXmlNode.children['recording']:
                    # Note that the lists below reflect https://musicbrainz.org/relationships/artist-recording
                    # Any changes to that DB structure will require changes
                    # here

                    # get recording artists data
                    recording_artist_list = parse_data(release_id, record, [], 'artist_credit', 'name_credit')
                    if recording_artist_list:
                        recording_artist = []
                        recording_artistsort = []
                        recording_artists = []
                        recording_artists_sort = []
                        locale = config.setting["artist_locale"]
                        # NB this is the Picard code in /util
                        lang = locale.split("_")[0]

                        # Set naming option
                        # Put naming style into preferential list

                        # naming as for vanilla Picard for track artists (per
                        # documentation rather than actual?)
                        if options['cea_ra_trackartist']:
                            if options['translate_artist_names'] and lang:
                                if options['standardize_artists']:
                                    name_style = ['alias', 'sort']
                                else:
                                    name_style = ['alias', 'credit', 'sort']
                            else:
                                if not options['standardize_artists']:
                                    name_style = ['credit']
                                else:
                                    name_style = []
                        # naming as for performers in classical extras
                        elif options['cea_ra_performer']:
                            if options['cea_aliases']:
                                if options['cea_alias_overrides']:
                                    name_style = ['alias', 'credit']
                                else:
                                    name_style = ['credit', 'alias']
                            else:
                                name_style = ['credit']

                        else:
                            name_style = []
                        if self.INFO:
                            write_log(release_id, 'info', 'Priority order of naming style for recording artists = %s',
                                      name_style)

                        styled_artists = apply_artist_style(options, release_id, lang, recording_artist_list,
                                                            name_style, recording_artist, recording_artistsort,
                                                            recording_artists, recording_artists_sort)
                        self.append_tag(release_id, tm, '~cea_recording_artists', styled_artists['artists'])
                        self.append_tag(release_id, tm, '~cea_recording_artists_sort', styled_artists['artists_sort'])
                        self.append_tag(release_id, tm, '~cea_recording_artist', styled_artists['artist'])
                        self.append_tag(release_id, tm, '~cea_recording_artistsort', styled_artists['artistsort'])

                    else:
                        tm['~cea_recording_artists'] = ''
                        tm['~cea_recording_artists_sort'] = ''
                        tm['~cea_recording_artist'] = ''
                        tm['~cea_recording_artistsort'] = ''

                    # use recording artist options
                    tm['~cea_MB_artist'] = tm['artist']
                    tm['~cea_MB_artistsort'] = tm['artistsort']
                    tm['~cea_MB_artists'] = tm['artists']
                    tm['~cea_MB_artists_sort'] = tm['~artists_sort']

                    if options['cea_ra_use']:
                        if options['cea_ra_replace_ta']:
                            if tm['~cea_recording_artist']:
                                tm['artist'] = tm['~cea_recording_artist']
                                tm['artistsort'] = tm['~cea_recording_artistsort']
                                tm['artists'] = tm['~cea_recording_artists']
                                tm['~artists_sort'] = tm['~cea_recording_artists_sort']
                            elif not options['cea_ra_noblank_ta']:
                                tm['artist'] = ''
                                tm['artistsort'] = ''
                                tm['artists'] = ''
                                tm['~artists_sort'] = ''
                        elif options['cea_ra_merge_ta']:
                            if tm['~cea_recording_artist']:
                                tm['artists'] = add_list_uniquely(
                                    tm['artists'], tm['~cea_recording_artists'])
                                tm['~artists_sort'] = add_list_uniquely(
                                    tm['~artists_sort'], tm['~cea_recording_artists_sort'])
                                if tm['artist'] != tm['~cea_recording_artist']:
                                    tm['artist'] = tm['artist'] + \
                                        ' (' + tm['~cea_recording_artist'] + ')'
                                    tm['artistsort'] = tm['artistsort'] + \
                                        ' (' + tm['~cea_recording_artistsort'] + ')'

                    # xml_type = 'recording'
                    relation_list = parse_data(release_id, record, [], 'relation_list')
                    performerList = album_performerList + \
                                    get_artists(options, release_id, tm, relation_list, 'recording')['artists']
                    # returns
                    # [(artist type, instrument or None, artist name, artist sort name, instrument sort, type sort)]
                    # where instrument sort places solo ahead of additional etc.
                    #  and type sort applies a custom sequencing to the artist types
                    if performerList:
                        if self.INFO:
                            write_log(release_id, 'info', "Performers: %s", performerList)
                        self.set_performer(release_id, album, track, performerList, tm)
                    if not options['classical_work_parts']:
                        work_artist_list = parse_data(release_id, record, [], 'relation_list',
                                                      'attribs.target_type:work', 'relation',
                                                      'attribs.type:performance', 'work', 'relation_list',
                                                      'attribs.target_type:artist')
                        work_artists = get_artists(options, release_id, tm, work_artist_list, 'work')['artists']
                        set_work_artists(self, release_id, album, track, work_artists, tm, 0)
                    # otherwise composers etc. will be set in work parts
            else:
                self.globals[track]['is_recording'] = False
        else:
            tm['000_major_warning'] = "WARNING: Classical Extras not run for this track as no file present - " \
                "deselect the option on the advanced tab to run. If there is a file, then try 'Refresh'."
        if track_metadata['tracknumber'] == track_metadata['totaltracks'] and track_metadata[
                'discnumber'] == track_metadata['totaldiscs']:  # last track
            self.process_album(release_id, album)
            close_log(release_id, 'artists')

    # Checks for ensembles
    def ensemble_type(self, performer):
        """
        Returns ensemble types
        :param performer:
        :return:
        """
        for ensemble_name in self.ORCHESTRAS:
            ensemble = re.compile(
                r'(.*)\b' +
                ensemble_name +
                r'\b(.*)',
                re.IGNORECASE)
            if ensemble.search(performer):
                return 'Orchestra'
        for ensemble_name in self.CHOIRS:
            ensemble = re.compile(
                r'(.*)\b' +
                ensemble_name +
                r'\b(.*)',
                re.IGNORECASE)
            if ensemble.search(performer):
                return 'Choir'
        for ensemble_name in self.GROUPS:
            ensemble = re.compile(
                r'(.*)\b' +
                ensemble_name +
                r'\b(.*)',
                re.IGNORECASE)
            if ensemble.search(performer):
                return 'Group'
        return False

    def process_album(self, release_id, album):
        """
        Perform final processing after all tracks read
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :return:
        """
        if self.DEBUG:
            write_log(release_id, 'debug', 'ExtraArtists: Starting process_album')
        # process lyrics tags
        if self.DEBUG:
            write_log(release_id, 'debug', 'Starting lyrics processing')
        common = []
        tmlyrics_dict = {}
        for track in self.track_listing[album]:
            options = self.options[track]
            if options['cea_split_lyrics'] and options['cea_lyrics_tag']:
                tm = track.metadata
                lyrics_tag = options['cea_lyrics_tag']
                if tm[lyrics_tag]:
                    # turn text into word lists to speed processing
                    tmlyrics_dict[track] = tm[lyrics_tag].split()
        if tmlyrics_dict:
            for item in tmlyrics_dict:
                write_log(release_id, 'info', 'tmlyrics_dict: track = %s, lyrics = %s', item, tmlyrics_dict[item])  # REMOVE
            tmlyrics_sort = sorted(tmlyrics_dict.items(), key=operator.itemgetter(1))
            for tup in tmlyrics_sort:
                write_log(release_id, 'info', 'tup in tmlyrics_sort = %s', tup)  # REMOVE
            prev = None
            first_track = None
            unique_lyrics = []
            ref_track = {}
            for lyric_tuple in tmlyrics_sort:  # tuple is (track, lyrics)
                if lyric_tuple[1] != prev:
                    unique_lyrics.append(lyric_tuple[1])
                    first_track = lyric_tuple[0]
                ref_track[lyric_tuple[0]] = first_track
                prev = lyric_tuple[1]
            write_log(release_id, 'info', 'Before turbo_lcs. Unique_lyrics = %r', unique_lyrics)  # REMOVE
            common = turbo_lcs(release_id, unique_lyrics)
            write_log(release_id, 'info', 'After turbo_lcs. Unique_lyrics = %r', unique_lyrics)  # REMOVE
            write_log(release_id, 'info', 'After turbo_lcs. lcs list = %s', common)  # REMOVE

        if common:
            unique = []
            for tup in tmlyrics_sort:
                track = tup[0]
                ref = ref_track[track]
                if track == ref:
                    indi = True
                else:
                    indi = False
                write_log(release_id, 'info', 'Ref track = %s, tup in tmlyrics_sort = %s', indi, tup)  # REMOVE
                if track == ref:
                    start = substart_finder(tup[1], common)
                    length = len(common)
                    end = min(start + length, len(tup[1]))
                    unique = tup[1][:start] + tup[1][end:]

                options = self.options[track]
                if options['cea_split_lyrics'] and options['cea_lyrics_tag']:
                    tm = track.metadata
                    if unique:
                        tm['~cea_track_lyrics'] = ' '.join(unique)
                    tm['~cea_album_lyrics'] = ' '.join(common)
                    if options['cea_album_lyrics']:
                        tm[options['cea_album_lyrics']] = tm['~cea_album_lyrics']
                    if unique and options['cea_track_lyrics']:
                        tm[options['cea_track_lyrics']] = tm['~cea_track_lyrics']
        else:
            for track in self.track_listing[album]:
                options = self.options[track]
                if options['cea_split_lyrics'] and options['cea_lyrics_tag']:
                    tm['~cea_track_lyrics'] = tm[options['cea_lyrics_tag']]
                    if options['cea_track_lyrics']:
                        tm[options['cea_track_lyrics']] = tm['~cea_track_lyrics']
        if self.DEBUG:
            write_log(release_id, 'debug', 'Ending lyrics processing')

        for track in self.track_listing[album]:
            options = self.options[track]
            tm = track.metadata
            tm['~cea_version'] = PLUGIN_VERSION
            blank_tags = options['cea_blank_tag'].split(
                ",") + options['cea_blank_tag_2'].split(",")

            # set work-type before any tags are blanked
            # Note that this is now mixed in with other sources of genres in def map_tags
            # ~cea_work_type_if_classical is used for types that are specifically classical
            # and is only applied in map_tags if the track is deemed to be classical
            if options['cwp_genres_infer']:
                if (self.globals[track]['is_recording'] and options['classical_work_parts']
                        and '~artists_sort' in tm and 'composersort' in tm
                        and any(x in tm['~artists_sort'] for x in tm['composersort'])
                        and 'writer' not in tm):
                    self.append_tag(release_id, tm, '~cea_work_type', 'Classical')

                if isinstance(tm['~cea_soloists'], basestring):
                    soloists = re.split(
                        '|'.join(
                            self.SEPARATORS),
                        tm['~cea_soloists'])
                else:
                    soloists = tm['~cea_soloists']
                if '~cea_vocalists' in tm:
                    if isinstance(tm['~cea_vocalists'], basestring):
                        vocalists = re.split(
                            '|'.join(
                                self.SEPARATORS),
                            tm['~cea_vocalists'])
                    else:
                        vocalists = tm['~cea_vocalists']
                else:
                    vocalists = []

                if '~cea_ensembles' in tm:
                    large = False
                    if 'performer:orchestra' in tm:
                        large = True
                        self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Orchestral')
                        if '~cea_soloists' in tm:
                            if 'vocals' in tm['~cea_instruments_all']:
                                self.append_tag(release_id, tm, '~cea_work_type', 'Vocal')
                            if len(soloists) == 1:
                                if soloists != vocalists:
                                    self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Concerto')
                                else:
                                    self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Aria')
                            elif len(soloists) == 2:
                                self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Duet')
                                if not vocalists:
                                    self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Concerto')
                            elif len(soloists) == 3:
                                self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Trio')
                            elif len(soloists) == 4:
                                self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Quartet')

                    if 'performer:choir' in tm or 'performer:choir vocals' in tm:
                        large = True
                        self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Choral')
                        self.append_tag(release_id, tm, '~cea_work_type', 'Vocal')
                    else:
                        if large and 'soloists' in tm and tm['soloists'].count(
                                'vocals') > 1:
                            self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Opera')
                    if not large:
                        if '~cea_soloists' not in tm:
                            self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Chamber music')
                        else:
                            if vocalists:
                                self.append_tag(release_id, tm, '~cea_work_type', 'Song')
                                self.append_tag(release_id, tm, '~cea_work_type', 'Vocal')
                            else:
                                self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Chamber music')
                else:
                    if len(soloists) == 1:
                            if vocalists != soloists:
                                self.append_tag(release_id, tm, '~cea_work_type', 'Instrumental')
                            else:
                                self.append_tag(release_id, tm, '~cea_work_type', 'Song')
                                self.append_tag(release_id, tm, '~cea_work_type', 'Vocal')
                    elif len(soloists) == 2:
                        self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Duet')
                    elif len(soloists) == 3:
                        self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Trio')
                    elif len(soloists) == 4:
                        self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Quartet')
                    else:
                        if not vocalists:
                            self.append_tag(release_id, tm, '~cea_work_type_if_classical', 'Chamber music')
                        else:
                            self.append_tag(release_id, tm, '~cea_work_type', 'Song')
                            self.append_tag(release_id, tm, '~cea_work_type', 'Vocal')
            # blank tags
            if 'artists_sort' in [x.strip() for x in blank_tags]:
                blank_tags.append('~artists_sort')
            for tag in blank_tags:
                if tag.strip() in tm:
                    # place blanked tags into hidden variables available for
                    # re-use
                    tm['~cea_' + tag.strip()] = tm[tag.strip()]
                    del tm[tag.strip()]

            # album
            if not options['classical_work_parts']:
                if 'composer_lastnames' in self.album_artists[album]:
                    last_names = seq_last_names(self, album)
                    self.append_tag(release_id, tm, '~cea_album_composer_lastnames', last_names)
            # otherwise this is done in the workparts class, which has all
            # composer info

            # process tag mapping
            tm['~cea_artists_complete'] = "Y"
            map_tags(options, release_id, album, tm)

            # write out options and errors/warnings to tags
            if options['cea_options_tag'] != "":
                self.cea_options = collections.defaultdict(
                    lambda: collections.defaultdict(
                        lambda: collections.defaultdict(dict)))

                for opt in plugin_options('artists') + plugin_options('picard'):
                    if 'name' in opt:
                        if 'value' in opt:
                            if options[opt['option']]:
                                self.cea_options['Classical Extras']['Artists options'][opt['name']] = opt['value']
                        else:
                            self.cea_options['Classical Extras']['Artists options'][opt['name']
                                                                                    ] = options[opt['option']]

                for opt in plugin_options('tag'):
                    if opt['option'] != "":
                        name_list = opt['name'].split("_")
                        self.cea_options['Classical Extras']['Artists options'][name_list[0]
                                                                                ][name_list[1]] = options[opt['option']]

                if options['ce_version_tag'] and options['ce_version_tag'] != "":
                    self.append_tag(release_id, tm, options['ce_version_tag'], unicode(
                        'Version ' +
                        tm['~cea_version'] +
                        ' of Classical Extras'))
                if options['cea_options_tag'] and options['cea_options_tag'] != "":
                    self.append_tag(release_id, tm, options['cea_options_tag'] +
                                    ':artists_options', json.loads(
                        json.dumps(
                            self.cea_options)))
        self.track_listing[album] = []
        if self.INFO:
            write_log(release_id, 'info', "FINISHED Classical Extra Artists. Album: %s", album)

    def append_tag(self, release_id, tm, tag, source):
        """
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param tm:
        :param tag:
        :param source:
        :return:
        """
        if self.INFO:
            write_log(release_id, 'info', "Extra Artists - appending %s to %s", source, tag)
        append_tag(release_id, tm, tag, source, self.SEPARATORS)

    def set_performer(self, release_id, album, track, performerList, tm):
        """
        Sets the performer-related tags
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :param track:
        :param performerList: see below
        :param tm:
        :return:
        """
        # performerList is in format [(artist_type, [instrument list],[name list],[sort_name list],
        # instrument_sort, type_sort),(.....etc]
        # Sorted by type_sort then sort name then instrument_sort
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Extra Artists - set_performer")
        if self.INFO:
            write_log(release_id, 'info', "Performer list is:")
            write_log(release_id, 'info', performerList)
        options = self.options[track]
        # tag strings are a tuple (Picard tag, cea tag, Picard sort tag, cea
        # sort tag)
        tag_strings = {'performer': ('performer:', '~cea_performers', '~performer_sort', '~cea_performers_sort'),
                       'instrument': ('performer:', '~cea_performers', '~performer_sort', '~cea_performers_sort'),
                       'vocal': ('performer:', '~cea_performers', '~performer_sort', '~cea_performers_sort'),
                       'performing orchestra': ('performer:orchestra', '~cea_ensembles', '~performer_sort',
                                                '~cea_ensembles_sort'),
                       'conductor': ('conductor', '~cea_conductors', '~conductor_sort', '~cea_conductors_sort'),
                       'chorus master': ('conductor', '~cea_chorusmasters', '~conductor_sort',
                                         '~cea_chorusmasters_sort'),
                       'concertmaster': ('performer', '~cea_leaders', '~performer_sort', '~cea_leaders_sort'),
                       'arranger': ('arranger', '~cea_arrangers', '_arranger_sort', '~cea_arrangers_sort'),
                       'instrument arranger': ('arranger', '~cea_arrangers', '~arranger_sort', '~cea_arrangers_sort'),
                       'orchestrator': ('arranger', '~cea_orchestrators', '~arranger_sort', '~cea_orchestrators_sort'),
                       'vocal arranger': ('arranger', '~cea_arrangers', '~arranger_sort', '~cea_arrangers_sort')
                       }
        # insertions lists artist types where names in the main Picard tags may be updated for annotations
        # (not for performer types as Picard will write performer:inst as Performer name (inst) )
        insertions = [
            'chorus master',
            'arranger',
            'instrument arranger',
            'orchestrator',
            'vocal arranger']

        # First remove all existing performer tags
        del_list = []
        for meta in tm:
            if 'performer' in meta:
                del_list.append(meta)
        for del_item in del_list:
            del tm[del_item]
        last_artist = []
        last_inst_list = []
        last_instrument = None
        artist_inst = []
        artist_inst_list = {}
        for performer in performerList:
            artist_type = performer[0]
            if artist_type not in tag_strings:
                return None
            if artist_type in ['instrument', 'vocal', 'performing orchestra']:
                if performer[1]:
                    inst_list = performer[1]
                    attrib_list = []
                    for attrib in ['solo', 'guest', 'additional']:
                        if attrib in inst_list:
                            inst_list.remove(attrib)
                            attrib_list.append(attrib)
                    attribs = " ".join(attrib_list)
                    instrument = ", ".join(inst_list)
                    if not options['cea_no_solo'] and attrib_list:
                        instrument = attribs + " " + instrument
                    if performer[3] == last_artist:
                        if instrument != last_instrument:
                            artist_inst.append(instrument)
                        else:
                            if inst_list == last_inst_list:
                                if self.WARNING or self.INFO:
                                    write_log(release_id, 'warning', 'Duplicated performer information for %s'
                                                                     ' (may be in Release Relationship as well as Track Relationship).'
                                                                     ' Duplicates have been ignored.', performer[3])
                                    self.append_tag(release_id, tm, '~cea_warning',
                                                    '2. Duplicated performer information for "' +
                                                    '; '.join(
                                                        performer[3]) +
                                                    '" (may be in Release Relationship as well as Track Relationship).'
                                                    ' Duplicates have been ignored.')
                    else:
                        artist_inst = [instrument]
                        last_artist = performer[3]
                        last_inst_list = inst_list
                        last_instrument = instrument

                    instrument = ", ".join(artist_inst)
                else:
                    instrument = None
                if artist_type == 'performing orchestra':
                    instrument = 'orchestra'
                artist_inst_list[tuple(performer[3])] = instrument
        for performer in performerList:
            artist_type = performer[0]
            if artist_type not in tag_strings:
                return None
            performing_artist = False if artist_type in [
                'arranger', 'instrument arranger', 'orchestrator', 'vocal arranger'] else True
            if True and artist_type in [
                'instrument',
                'vocal',
                    'performing orchestra']:  # There may be an option here (to replace 'True')
                # Currently groups instruments by artist - alternative has been
                # tested if required
                instrument = artist_inst_list[tuple(performer[3])]
            else:
                if performer[1]:
                    inst_list = performer[1]
                    if options['cea_no_solo']:
                        for attrib in ['solo', 'guest', 'additional']:
                            if attrib in inst_list:
                                inst_list.remove(attrib)
                    instrument = " ".join(inst_list)
                else:
                    instrument = None
                if artist_type == 'performing orchestra':
                    instrument = 'orchestra'
            sub_strings = {'instrument': instrument,
                           'vocal': instrument  # ,
                           # 'instrument arranger': instrument,
                           # 'vocal arranger': instrument
                           }
            for typ in ['concertmaster']:
                if options['cea_' + typ] and options['cea_arrangers']:
                    sub_strings[typ] = ':' + options['cea_' + typ]

            if options['cea_arranger']:
                if instrument:
                    arr_inst = options['cea_arranger'] + ' ' + instrument
                else:
                    arr_inst = options['cea_arranger']
            else:
                arr_inst = instrument
            annotations = {'instrument': instrument,
                           'vocal': instrument,
                           'performing orchestra': instrument,
                           'chorus master': options['cea_chorusmaster'],
                           'concertmaster': options['cea_concertmaster'],
                           'arranger': options['cea_arranger'],
                           'instrument arranger': arr_inst,
                           'orchestrator': options['cea_orchestrator'],
                           'vocal arranger': arr_inst}
            tag = tag_strings[artist_type][0]
            cea_tag = tag_strings[artist_type][1]
            sort_tag = tag_strings[artist_type][2]
            cea_sort_tag = tag_strings[artist_type][3]
            cea_names_tag = cea_tag[:-1] + '_names'
            cea_instrumented_tag = cea_names_tag + '_instrumented'
            if artist_type in sub_strings:
                if sub_strings[artist_type]:
                    tag += sub_strings[artist_type]
                else:
                    if self.WARNING or self.INFO:
                        write_log(release_id, 'warning',
                                  'No instrument/sub-key available for artist_type %s. Performer = %s. Track is %s',
                                  artist_type, performer[2], track)

            if tag:
                if '~ce_tag_cleared_' + \
                        tag not in tm or not tm['~ce_tag_cleared_' + tag] == "Y":
                    if tag in tm:
                        if self.INFO:
                            write_log(release_id, 'info', 'delete tag %s', tag)
                        del tm[tag]
                tm['~ce_tag_cleared_' + tag] = "Y"
            if sort_tag:
                if '~ce_tag_cleared_' + \
                        sort_tag not in tm or not tm['~ce_tag_cleared_' + sort_tag] == "Y":
                    if sort_tag in tm:
                        del tm[sort_tag]
                tm['~ce_tag_cleared_' + sort_tag] = "Y"

            name_list = performer[2]
            for ind, name in enumerate(name_list):
                performer_type = ''
                sort_name = performer[3][ind]
                no_credit = True
                # change name to as-credited
                if (performing_artist and options['cea_performer_credited'] or
                        not performing_artist and options['cea_composer_credited']):
                    if sort_name in self.artist_credits[album]:
                        no_credit = False
                        name = self.artist_credits[album][sort_name]
                # over-ride with aliases and use standard MB name (not
                # as-credited) if no alias
                if (options['cea_aliases'] or not performing_artist and options['cea_aliases_composer']) and (
                        no_credit or options['cea_alias_overrides']):
                    if sort_name in self.artist_aliases:
                        name = self.artist_aliases[sort_name]
                # fix cyrillic names if not already fixed
                if options['cea_cyrillic']:
                    if not only_roman_chars(name):
                        name = remove_middle(unsort(sort_name))
                        # Only remove middle name where the existing
                        # performer is in non-latin script
                annotated_name = name
                if instrument:
                    instrumented_name = name + ' (' + instrument + ')'
                else:
                    instrumented_name = name
                # add annotations and write performer tags
                if artist_type in annotations:
                    if annotations[artist_type]:
                        annotated_name += ' (' + annotations[artist_type] + ')'
                    else:
                        if self.WARNING or self.INFO:
                            write_log(release_id, 'warning',
                                      'No annotation (instrument) available for artist_type %s.'
                                      ' Performer = %s. Track is %s', artist_type, performer[2], track)
                if artist_type in insertions and options['cea_arrangers']:
                    self.append_tag(release_id, tm, tag, annotated_name)
                else:
                    if options['cea_arrangers'] or artist_type == tag:
                        self.append_tag(release_id, tm, tag, name)

                if options['cea_arrangers'] or artist_type == tag:
                    if sort_tag:
                        self.append_tag(release_id, tm, sort_tag, sort_name)
                        if options['cea_tag_sort'] and '~' in sort_tag:
                            explicit_sort_tag = sort_tag.replace('~', '')
                            self.append_tag(release_id, tm, explicit_sort_tag, sort_name)

                self.append_tag(release_id, tm, cea_tag, annotated_name)
                # if artist_type not in [
                #         'instrument', 'vocal', 'performing orchestra']:
                #     self.append_tag(tm, cea_names_tag, instrumented_name)
                # else:
                #     self.append_tag(tm, cea_names_tag, name)
                self.append_tag(release_id, tm, cea_names_tag, name)
                if instrumented_name != name:
                    self.append_tag(release_id, tm, cea_instrumented_tag, instrumented_name)

                if cea_sort_tag:
                    self.append_tag(release_id, tm, cea_sort_tag, sort_name)

                # differentiate soloists etc and write related tags
                if artist_type == 'performing orchestra' or (
                        instrument and instrument in self.ENSEMBLE_TYPES) or self.ensemble_type(name):
                    performer_type = 'ensembles'
                    self.append_tag(release_id, tm, '~cea_ensembles', instrumented_name)
                    self.append_tag(release_id, tm, '~cea_ensemble_names', name)
                    self.append_tag(release_id, tm, '~cea_ensembles_sort', sort_name)
                elif artist_type in ['performer', 'instrument', 'vocal']:
                    performer_type = 'soloists'
                    self.append_tag(release_id, tm, '~cea_soloists', instrumented_name)
                    self.append_tag(release_id, tm, '~cea_soloist_names', name)
                    self.append_tag(release_id, tm, '~cea_soloists_sort', sort_name)
                    if artist_type == "vocal":
                        self.append_tag(release_id, tm, '~cea_vocalists', instrumented_name)
                        self.append_tag(release_id, tm, '~cea_vocalist_names', name)
                        self.append_tag(release_id, tm, '~cea_vocalists_sort', sort_name)
                    elif instrument:
                        self.append_tag(release_id, tm, '~cea_instrumentalists', instrumented_name)
                        self.append_tag(release_id, tm, '~cea_instrumentalist_names', name)
                        self.append_tag(release_id, tm, '~cea_instrumentalists_sort', sort_name)
                    else:
                        self.append_tag(release_id, tm, '~cea_other_soloists', instrumented_name)
                        self.append_tag(release_id, tm, '~cea_other_soloist_names', name)
                        self.append_tag(release_id, tm, '~cea_other_soloists_sort', sort_name)

                # set album artists
                if performer_type or artist_type == 'conductor':
                    cea_album_tag = cea_tag.replace(
                        'cea', 'cea_album').replace(
                        'performers', performer_type)
                    cea_album_sort_tag = cea_sort_tag.replace(
                        'cea', 'cea_album').replace(
                        'performers', performer_type)
                    if stripsir(name) in tm['~albumartists'] or stripsir(
                            sort_name) in tm['~albumartists_sort']:
                        self.append_tag(release_id, tm, cea_album_tag, name)
                        self.append_tag(release_id, tm, cea_album_sort_tag, sort_name)
                    else:
                        if performer_type:
                            self.append_tag(release_id, tm, '~cea_support_performers', instrumented_name)
                            self.append_tag(release_id, tm, '~cea_support_performer_names', name)
                            self.append_tag(release_id, tm, '~cea_support_performers_sort', sort_name)

##############
##############
# WORK PARTS #
##############
##############


class PartLevels():
    # QUEUE-HANDLING
    class WorksQueue(LockableObject):
        """Object for managing the queue of lookups"""

        def __init__(self):
            LockableObject.__init__(self)
            self.queue = {}

        def __contains__(self, name):
            return name in self.queue

        def __iter__(self):
            return self.queue.__iter__()

        def __getitem__(self, name):
            self.lock_for_read()
            value = self.queue[name] if name in self.queue else None
            self.unlock()
            return value

        def __setitem__(self, name, value):
            self.lock_for_write()
            self.queue[name] = value
            self.unlock()

        def append(self, name, value):
            self.lock_for_write()
            if name in self.queue:
                self.queue[name].append(value)
                value = False
            else:
                self.queue[name] = [value]
                value = True
            self.unlock()
            return value

        def remove(self, name):
            self.lock_for_write()
            value = None
            if name in self.queue:
                value = self.queue[name]
                del self.queue[name]
            self.unlock()
            return value

        # INITIALISATION

    def __init__(self):
        self.works_cache = {}
        # maintains list of parent of each workid, or None if no parent found,
        # so that XML lookup need only executed if no existing record
        self.partof = collections.defaultdict(dict)
        # the inverse of the above (immediate children of each parent)
        # but note that this is specific to the album as children may vary between albums
        # so format is {album1{parent1: child1, parent2:, child2},
        # album2{....}}
        self.works_queue = self.WorksQueue()
        # lookup queue - holds track/album pairs for each queued workid (may be
        # more than one pair per id, especially for higher-level parts)
        self.parts = collections.defaultdict(
            lambda: collections.defaultdict(dict))
        # metadata collection for all parts - structure is {workid: {name: ,
        # parent: , (track,album): {part_levels}}, etc}
        self.top_works = collections.defaultdict(dict)
        # metadata collection for top-level works for (track, album) -
        # structure is {(track, album): {workId: }, etc}
        self.trackback = collections.defaultdict(
            lambda: collections.defaultdict(dict))
        # hierarchical iterative work structure - {album: {id: , children:{id:
        # , children{}, id: etc}, id: etc} }
        self.work_listing = collections.defaultdict(list)
        # contains list of workIds for each album
        self.top = collections.defaultdict(list)
        # self.top[album] = list of work Ids which are top-level works in album
        self.options = collections.defaultdict(dict)
        # currently active Classical Extras options
        self.file_works = collections.defaultdict(list)
        # list of works derived from SongKong-style file tags
        # structure is {(album, track): [{workid: , name: }, {workid: ....}}
        self.album_artists = collections.defaultdict(
            lambda: collections.defaultdict(dict))
        # collection of artists to be applied at album level
        self.artist_aliases = {}
        # collection of alias names - format is {sort_name: alias_name, ...}
        self.artist_credits = collections.defaultdict(dict)
        # collection of credited-as names - format is {album: {sort_name: credit_name,
        # ...}, ...}
        self.release_artists_sort = collections.defaultdict(list)
        # collection of release artists - format is {album: [sort_name_1,
        # sort_name_2, ...]}
        self.lyricist_filled = collections.defaultdict(dict)
        # Boolean for each track to indicate if lyricist has been found (don't
        # want to add more from higher levels)
        self.orphan_tracks = collections.defaultdict(list)
        # To keep a list for each album of tracks which do not have works -
        # format is {album: [track1, track2, ...], etc}
        self.tracks = collections.defaultdict(list)
        # To keep a list of all tracks for the album - format is {album:
        # [track1, track2, ...], etc}

    ########################################
    # SECTION 1 - Initial track processing #
    ########################################

    def add_work_info(
            self,
            album,
            track_metadata,
            trackXmlNode,
            releaseXmlNode):
        """
        Main Routine - run for each track
        :param album:
        :param track_metadata:
        :param trackXmlNode:
        :param releaseXmlNode:
        :return:
        """
        release_id = track_metadata['musicbrainz_albumid']
        if 'start' not in release_status[release_id]:
            release_status[release_id]['start'] = datetime.now()
        if 'lookups' not in release_status[release_id]:
            release_status[release_id]['lookups'] = 0
        release_status[release_id]['name'] = track_metadata['album']
        release_status[release_id]['works'] = True
        write_log(release_id, 'debug', 'STARTING WORKS PROCESSING FOR ALBUM %s, TRACK %s',
                  track_metadata['album'], track_metadata['tracknumber'] + ' ' + track_metadata['title'])
        # clear the cache if required (if this is not done, then queue count may get out of sync)
        # Jump through hoops to get track object!!
        track = album._new_tracks[-1]
        tm = track.metadata
        if config.setting['log_debug']:
            write_log(release_id, 'debug', 'Cache setting for track %s is %s', track,
                      config.setting['use_cache'])

        # OPTIONS - OVER-RIDE IF REQUIRED
        if '~ce_options' not in tm:
            write_log(release_id, 'debug', 'Workparts gets track first...')
            get_options(release_id, album, track)
        options = interpret(tm['~ce_options'])

        if not options:
            if config.setting["log_error"]:
                write_log(release_id, 'error', 'Work Parts. Failure to read saved options for track %s. options = %s',
                          track, tm['~ce_options'])
            options = option_settings(config.setting)
        self.options[track] = options

        # CONSTANTS
        self.ERROR = options["log_error"]
        self.WARNING = options["log_warning"]
        self.DEBUG = options["log_debug"]
        self.INFO = options["log_info"]
        self.SEPARATORS = ['; ']
        self.EQ = "EQ_TO_BE_REVERSED"  # phrase to indicate that a synonym has been used

        self.get_sk_tags(release_id, album, track, tm, options)

        # Continue?
        if not options["classical_work_parts"]:
            return

        # OPTION-DEPENDENT CONSTANTS:
        # Maximum number of XML- lookup retries if error returned from server
        self.MAX_RETRIES = options["cwp_retries"]
        self.USE_CACHE = options["use_cache"]
        if options["cwp_partial"] and options["cwp_partial_text"] and options["cwp_level0_works"]:
            options["cwp_removewords_p"] = options["cwp_removewords"] + \
                ", " + options["cwp_partial_text"] + ' '
        else:
            options["cwp_removewords_p"] = options["cwp_removewords"]
        # Explanation:
        # If "Partial" is selected then the level 0 work name will have PARTIAL_TEXT appended to it.
        # If a recording is split across several tracks then each sub-part (quasi-movement) will have the same name
        # (with the PARTIAL_TEXT added). If level 0 is used to source work names then the level 1 work name will be
        # changed to be this repeated name and will therefore also include PARTIAL_TEXT.
        # So we need to add PARTIAL_TEXT to the prefixes list to ensure it is
        # excluded from the level 1  work name.
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "PartLevels - LOAD NEW TRACK: :%s", track)

        # first time for this album (reloads each refresh)
        if tm['discnumber'] == '1' and tm['tracknumber'] == '1':
            # get artist aliases - these are cached so can be re-used across
            # releases, but are reloaded with each refresh
            get_aliases(self, release_id, album, options, releaseXmlNode)

        # fix titles which include composer name
        composersort = dict.get(track_metadata, 'composersort', [])
        composerlastnames = []
        for composer in composersort:
            lname = re.compile(r'(.*),')
            match = lname.search(composer)
            if match:
                composerlastnames.append(match.group(1))
            else:
                composerlastnames.append(composer)
        title = track_metadata['title']
        colons = title.count(":")
        if colons > 0:
            title_split = title.split(': ', 1)
            test = title_split[0]
            if test in composerlastnames:
                track_metadata['~cwp_title'] = title_split[1]

        # now process works
        write_log(release_id, 'info', 'PartLevels - add_work_info - metadata load = %r', track_metadata)
        workIds = dict.get(track_metadata, 'musicbrainz_workid', [])
        if workIds and not (options["ce_no_run"] and (
                not tm['~ce_file'] or tm['~ce_file'] == "None")):
            # works = dict.get(track_metadata, 'work', [])
            work_list_info = []
            keyed_workIds = {}
            for i, workId in enumerate(workIds):

                # sort by ordering_key, if any
                match_tree = [
                    'recording',
                    'relation_list',
                    'attribs.target_type:work',
                    'relation',
                    'target.text:' + workId]
                rels = parse_data(release_id, trackXmlNode, [], *match_tree)
                # for recordings which are ordered within track:-
                match_tree_1 = [
                    'ordering_key',
                    'text']
                # for recordings of works which are ordered as part of parent
                # (may be duplicated by top-down check later):-
                match_tree_2 = [
                    'work',
                    'relation_list',
                    'attribs.target_type:work',
                    'relation',
                    'attribs.type:parts',
                    'direction.text:backward',
                    'ordering_key',
                    'text']
                parse_result = parse_data(release_id, rels, [], *match_tree_1) + parse_data(release_id, rels, [],
                                                                                            *match_tree_2)
                if self.INFO:
                    write_log(release_id, 'info', 'multi-works - ordering key: %s', parse_result)
                if parse_result and parse_result[0].isdigit():
                    key = int(parse_result[0])
                else:
                    key = 'no key - id seq: ' + unicode(i)
                keyed_workIds[key] = workId
            partial = False
            for key in sorted(keyed_workIds.iterkeys()):
                workId = keyed_workIds[key]
                work_rels = parse_data(release_id, trackXmlNode, [], 'recording', 'relation_list',
                                       'attribs.target_type:work', 'relation', 'target.text:' +
                                       workId)
                work_attributes = parse_data(release_id, work_rels, [], 'attribute_list', 'attribute', 'text')
                work_titles = parse_data(release_id, work_rels, [], 'work', 'attribs.id:' +
                                         workId, 'title', 'text')
                work_list_info_item = {
                    'id': workId,
                    'attributes': work_attributes,
                    'titles': work_titles}
                work_list_info.append(work_list_info_item)
                work = []
                for title in work_titles:
                    work.append(title)

                if options['cwp_partial']:
                    # treat the recording as work level 0 and the work of which it
                    # is a partial recording as work level 1
                    if 'partial' in work_attributes:
                        partial = True
                        parentId = workId
                        workId = track_metadata['musicbrainz_recordingid']

                        works = []
                        for w in work:
                            partwork = w
                            works.append(partwork)

                        if self.INFO:
                            write_log(release_id, 'info', "Id %s is PARTIAL RECORDING OF id: %s, name: %s",
                                      workId, parentId, work)
                        work_list_info_item = {
                            'id': workId,
                            'attributes': [],
                            'titles': works,
                            'parent': parentId}
                        work_list_info.append(work_list_info_item)
            if self.INFO:
                write_log(release_id, 'info', 'work_list_info: %s', work_list_info)
            # we now have a list of items, where the id of each is a work id for the track or
            #  (multiple instances of) the recording id (for partial works)
            # we need to turn this into a usable hierarchy - i.e. just one item
            workId_list = []
            work_list = []
            parent_list = []
            attribute_list = []
            workId_list_p = []
            work_list_p = []
            attribute_list_p = []
            for w in work_list_info:
                if 'partial' not in w['attributes'] or not options[
                        'cwp_partial']:  # just do the bottom-level 'works' first
                    workId_list.append(w['id'])
                    work_list += w['titles']
                    attribute_list += w['attributes']
                    if 'parent' in w:
                        if w['parent'] not in parent_list:  # avoid duplicating parents!
                            parent_list.append(w['parent'])
                else:
                    workId_list_p.append(w['id'])
                    work_list_p += w['titles']
                    attribute_list_p += w['attributes']
            # de-duplicate work names
            # list(set()) won't work as need to retain order
            work_list = list(collections.OrderedDict.fromkeys(work_list))
            work_list_p = list(collections.OrderedDict.fromkeys(work_list_p))

            workId_tuple = tuple(workId_list)
            workId_tuple_p = tuple(workId_list_p)
            if workId_tuple not in self.work_listing[album]:
                self.work_listing[album].append(workId_tuple)
            if workId_tuple not in self.parts or not self.USE_CACHE:
                self.parts[workId_tuple]['name'] = work_list
                if parent_list:
                    if workId_tuple in self.works_cache:
                        self.works_cache[workId_tuple] += parent_list
                        self.parts[workId_tuple]['parent'] += parent_list
                    else:
                        self.works_cache[workId_tuple] = parent_list
                        self.parts[workId_tuple]['parent'] = parent_list
                    self.parts[workId_tuple_p]['name'] = work_list_p
                    if workId_tuple_p not in self.work_listing[album]:
                        self.work_listing[album].append(workId_tuple_p)

                if 'medley' in attribute_list_p:
                    self.parts[workId_tuple_p]['medley'] = True

                if 'medley' in attribute_list:
                    self.parts[workId_tuple]['medley'] = True

                if partial:
                    self.parts[workId_tuple]['partial'] = True

            self.trackback[album][workId_tuple]['id'] = workId_list
            if 'meta' in self.trackback[album][workId_tuple]:
                if (track,
                        album) not in self.trackback[album][workId_tuple]['meta']:
                    self.trackback[album][workId_tuple]['meta'].append(
                        (track, album))
            else:
                self.trackback[album][workId_tuple]['meta'] = [(track, album)]
            if self.INFO:
                write_log(release_id, 'info', "Trackback for %s is %s. Partial = %s", track,
                          self.trackback[album][workId_tuple], partial)

            if workId_tuple in self.works_cache and (
                    self.USE_CACHE or partial):
                if self.DEBUG or self.INFO:
                    write_log(release_id, 'debug', "GETTING WORK METADATA FROM CACHE, for work %s", workId_tuple)
                if workId_tuple not in self.work_listing[album]:
                    self.work_listing[album].append(workId_tuple)
                not_in_cache = self.check_cache(
                    track_metadata, album, track, workId_tuple, [])
            else:
                if partial:
                    not_in_cache = [workId_tuple_p]
                else:
                    not_in_cache = [workId_tuple]
            for workId_tuple in not_in_cache:
                if not self.USE_CACHE:
                    if workId_tuple in self.works_cache:
                        del self.works_cache[workId_tuple]
                self.work_not_in_cache(release_id, album, track, workId_tuple)

        else:  # no work relation
            if self.WARNING or self.INFO:
                write_log(release_id, 'warning', "WARNING - no works for this track: \"%s\"", title)
            self.append_tag(release_id, track_metadata, '~cwp_warning', '3. No works for this track')
            if album in self.orphan_tracks:
                if track not in self.orphan_tracks[album]:
                    self.orphan_tracks[album].append(track)
            else:
                self.orphan_tracks[album] = [track]
            # Don't publish metadata yet until all album is processed

        # last track
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug',
                      'Check for last track. Requests = %s, Tracknumber = %s, Totaltracks = %s,'
                      ' Discnumber = %s, Totaldiscs = %s', album._requests, track_metadata['tracknumber'],
                      track_metadata['totaltracks'], track_metadata['discnumber'], track_metadata['totaldiscs'])
        if album._requests == 0 and track_metadata['tracknumber'] == track_metadata[
                'totaltracks'] and track_metadata['discnumber'] == track_metadata['totaldiscs']:
            self.process_album(release_id, album)
            close_log(release_id, 'works')

    def get_sk_tags(self, release_id, album, track, tm, options):
        """
        Get file tags which are consistent with SongKong's metadata usage
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :param track:
        :param tm:
        :param options:
        :return:
        """
        if options["cwp_use_sk"]:
            if '~ce_file' in tm and interpret(tm['~ce_file']):
                music_file = tm['~ce_file']
                orig_metadata = album.tagger.files[music_file].orig_metadata
                if 'musicbrainz_work_composition_id' in orig_metadata and 'musicbrainz_workid' in orig_metadata:
                    if 'musicbrainz_work_composition' in orig_metadata:
                        if 'musicbrainz_work' in orig_metadata:
                            if orig_metadata['musicbrainz_work_composition_id'] == orig_metadata[
                                'musicbrainz_workid'] \
                                    and orig_metadata['musicbrainz_work_composition'] != orig_metadata[
                                        'musicbrainz_work']:
                                # Picard may have overwritten SongKong tag (top
                                # work id) with bottom work id
                                if self.WARNING or self.INFO:
                                    write_log(release_id, 'warning',
                                              'File tag musicbrainz_workid incorrect? id = %s. Sourcing from MB',
                                              orig_metadata['musicbrainz_workid'])
                                self.append_tag(release_id, tm, '~cwp_warning',
                                                '4. File tag musicbrainz_workid incorrect? id = ' +
                                                orig_metadata['musicbrainz_workid'] +
                                                '. Sourcing from MB')
                                return None
                        if self.INFO:
                            write_log(release_id, 'info', 'Read from file tag: musicbrainz_work_composition_id: %s',
                                      orig_metadata['musicbrainz_work_composition_id'])
                        self.file_works[(album, track)].append({
                            'workid': orig_metadata['musicbrainz_work_composition_id'].split('; '),
                            'name': orig_metadata['musicbrainz_work_composition']})
                    else:
                        wid = orig_metadata['musicbrainz_work_composition_id']
                        if self.ERROR or self.INFO:
                            write_log(release_id, 'error', "No matching work name for id tag %s", wid)
                        self.append_tag(release_id, tm, '~cwp_error', '2. No matching work name for id tag ' + wid)
                        return None
                    n = 1
                    while 'musicbrainz_work_part_level' + \
                            unicode(n) + '_id' in orig_metadata:
                        if 'musicbrainz_work_part_level' + \
                                unicode(n) in orig_metadata:
                            self.file_works[(album, track)].append({
                                'workid': orig_metadata[
                                    'musicbrainz_work_part_level' + unicode(n) + '_id'].split('; '),
                                'name': orig_metadata['musicbrainz_work_part_level' + unicode(n)]})
                            n += 1
                        else:
                            wid = orig_metadata['musicbrainz_work_part_level' +
                                                unicode(n) + '_id']
                            if self.ERROR or self.INFO:
                                write_log(release_id, 'error', "No matching work name for id tag %s",
                                          wid)
                            self.append_tag(release_id, tm, '~cwp_error', '2. No matching work name for id tag ' + wid)
                            break
                    if orig_metadata['musicbrainz_work_composition_id'] != orig_metadata[
                            'musicbrainz_workid']:
                        if 'musicbrainz_work' in orig_metadata:
                            self.file_works[(album, track)].append({
                                'workid': orig_metadata['musicbrainz_workid'].split('; '),
                                'name': orig_metadata['musicbrainz_work']})
                        else:
                            wid = orig_metadata['musicbrainz_workid']
                            if self.ERROR or self.INFO:
                                write_log(release_id, 'error', "No matching work name for id tag %s", wid)
                            self.append_tag(release_id, tm, '~cwp_error', '2. No matching work name for id tag ' + wid)
                            return None
                    file_work_levels = len(self.file_works[(album, track)])
                    if self.DEBUG or self.INFO:
                        write_log(release_id, 'debug', 'Loaded works from file tags for track %s. Works: %s: ',
                                  track, self.file_works[(album, track)])
                    for i, work in enumerate(self.file_works[(album, track)]):
                        workId = tuple(work['workid'])
                        if workId not in self.works_cache:  # Use cache in preference to file tags
                            if workId not in self.work_listing[album]:
                                self.work_listing[album].append(workId)
                            self.parts[workId]['name'] = [work['name']]
                            parentId = None
                            parent = ''
                            if i < file_work_levels - 1:
                                parentId = self.file_works[(
                                    album, track)][i + 1]['workid']
                                parent = self.file_works[(
                                    album, track)][i + 1]['name']

                            if parentId:
                                self.works_cache[workId] = parentId
                                self.parts[workId]['parent'] = parentId
                                self.parts[tuple(parentId)]['name'] = [parent]
                            else:
                                # so we remember we looked it up and found none
                                self.parts[workId]['no_parent'] = True
                                self.top_works[(track, album)
                                               ]['workId'] = workId
                                if workId not in self.top[album]:
                                    self.top[album].append(workId)

    def check_cache(self, tm, album, track, workId_tuple, not_in_cache):
        """
        Recursive loop to get cached works
        :param tm:
        :param album:
        :param track:
        :param workId_tuple:
        :param not_in_cache:
        :return:
        """
        parentId_tuple = tuple(self.works_cache[workId_tuple])
        if parentId_tuple not in self.work_listing[album]:
            self.work_listing[album].append(parentId_tuple)

        if parentId_tuple in self.works_cache:
            self.check_cache(tm, album, track, parentId_tuple, not_in_cache)
        else:
            not_in_cache.append(parentId_tuple)
        return not_in_cache

    def work_not_in_cache(self, release_id, album, track, workId_tuple):
        """
        Determine actions if work not in cache (is it the top or do we need to look up?)
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :param track:
        :param workId_tuple:
        :return:
        """
        write_log(release_id, 'debug', 'Processing work_not_in_cache for workId %s', workId_tuple)
        if 'no_parent' in self.parts[workId_tuple] and (
                self.USE_CACHE or self.options[track]["cwp_use_sk"]) and self.parts[workId_tuple]['no_parent']:
            write_log(release_id, 'info', '%s is top work', workId_tuple)
            self.top_works[(track, album)]['workId'] = workId_tuple
            if album in self.top:
                if workId_tuple not in self.top[album]:
                    self.top[album].append(workId_tuple)
            else:
                self.top[album] = [workId_tuple]
        else:
            write_log(release_id, 'info', 'Calling work_add_track to look up parents for %s', workId_tuple)
            for workId in workId_tuple:
                self.work_add_track(album, track, workId, 0)
        write_log(release_id, 'debug', 'End of work_not_in_cache for workId %s', workId_tuple)

    def work_add_track(self, album, track, workId, tries, user_data=True):
        """
        Add the work to the lookup queue
        :param user_data:
        :param album:
        :param track:
        :param workId:
        :param tries: number of lookup attempts
        :return:
        """
        release_id = track.metadata['musicbrainz_albumid']
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "ADDING WORK TO LOOKUP QUEUE for work %s", workId)
        self.album_add_request(release_id, album)
        # to change the _requests variable to indicate that there are pending
        # requests for this item and delay Picard from finalizing the album
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Added lookup request for id %s. Requests = %s", workId,
                      album._requests)
        if self.works_queue.append(
                workId,
                (track,
                 album)):  # All work combos are queued, but only new workIds are passed to XML lookup
            host = config.setting["server_host"]
            port = config.setting["server_port"]
            path = "/ws/2/%s/%s" % ('work', workId)
            if config.setting['cwp_aliases'] and config.setting['cwp_aliases_tag_text']:
                if config.setting['cwp_aliases_tags_user'] and user_data:
                    login = True
                    tag_type = '+tags +user-tags'
                else:
                    login = False
                    tag_type = '+tags'
            else:
                login = False
                tag_type = ''
            queryargs = {"inc": "work-rels+artist-rels+label-rels+place-rels+aliases" + tag_type}
            if self.DEBUG or self.INFO:
                write_log(release_id, 'debug', "Initiating XML lookup for %s......", workId)
            if release_id in release_status and 'lookups' in release_status[release_id]:
                release_status[release_id]['lookups'] += 1
            return album.tagger.xmlws.get(
                host,
                port,
                path,
                partial(
                    self.work_process,
                    workId,
                    tries),
                xml=True,
                priority=True,
                important=False,
                mblogin=login,
                queryargs=queryargs)
        else:
            if self.DEBUG or self.INFO:
                write_log(release_id, 'debug', "Work is already in queue: %s", workId)

    #####################################################################################
    # SECTION 2 - Works processing                                                      #
    # NB These functions may operate over multiple albums (as well as multiple tracks)  #
    #####################################################################################

    def work_process(self, workId, tries, response, reply, error):
        """
        Top routine to process the XML node response from the lookup
        NB This function may operate over multiple albums (as well as multiple tracks)
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param workId:
        :param tries:
        :param response:
        :param reply:
        :param error:
        :return:
        """
        if error:
            tuples = self.works_queue.remove(workId)
            for track, album in tuples:
                release_id = track.metadata['musicbrainz_albumid']
                if self.WARNING or self.INFO:
                    write_log(release_id, 'warning', "%r: Network error retrieving work record. Error code %r",
                              workId, error)
                if self.DEBUG or self.INFO:
                    write_log(release_id, 'debug', "Removed request after network error. Requests = %s",
                              album._requests)
                if tries < self.MAX_RETRIES:
                    user_data = True
                    if self.DEBUG or self.INFO:
                        write_log(release_id, 'debug', "REQUEUEING...")
                    if str(error) == '204':  # Authentication error
                        if self.DEBUG or self.INFO:
                            write_log(release_id, 'debug', "... without user authentication")
                        user_data = False
                        self.append_tag(release_id, track.metadata, '~cwp_error',
                                        '3. Authentication failure - data retrieval omits user-specific requests')
                    self.work_add_track(album, track, workId, tries + 1, user_data)
                else:
                    if self.ERROR or self.INFO:
                        write_log(release_id, 'error', "EXHAUSTED MAX RE-TRIES for XML lookup for track %s", track)
                        self.append_tag(release_id, track.metadata, '~cwp_error',
                                        "4. ERROR: MISSING METADATA due to network errors. Re-try or fix manually.")
                self.album_remove_request(release_id, album)
            return
        tuples = self.works_queue.remove(workId)
        # if self.INFO:
        #     write_log('session', 'info', 'Found work id %s. Tuples are %r', workId, tuples)
        if tuples:
            new_queue = []
            prev_album = None
            for tup_num, (track, album) in enumerate(tuples):
                release_id = track.metadata['musicbrainz_albumid']
                # Note that this need to be set here as the work may cover multiple albums
                if album != prev_album:
                    write_log(release_id, 'debug',
                              "Work_process. FOUND WORK: %s for album %s",
                              workId, album)
                    write_log(release_id, 'debug', "Requests for album %s = %s", album, album._requests)
                prev_album = album
                if self.INFO:
                    write_log(release_id, 'info', "RESPONSE = %s", response)
                # find the id_tuple(s) key with workId in it
                wid_list = []
                for w in self.work_listing[album]:
                    if workId in w and w not in wid_list:
                        wid_list.append(w)
                if self.INFO:
                    write_log(release_id, 'info', 'wid_list for %s is %s', workId, wid_list)
                for wid in wid_list:  # wid is a tuple
                    write_log(release_id, 'info', 'processing workId tuple: %r', wid)
                    metaList = self.work_process_metadata(release_id, workId, wid, track, response)
                    parentList = metaList[0]
                    # returns [parent id, parent name] or None if no parent found
                    arrangers = metaList[1]
                    # not just arrangers - also composers, lyricists etc.
                    if wid in self.parts:

                        if arrangers:
                            if 'arrangers' in self.parts[wid]:
                                self.parts[wid]['arrangers'] += arrangers
                            else:
                                self.parts[wid]['arrangers'] = arrangers

                        if parentList:
                            # first fix the sort order of multi-works at the prev
                            # level
                            if len(wid) > 1:
                                for idx in wid:
                                    if idx == workId:
                                        match_tree = [
                                            'metadata',
                                            'work',
                                            'relation_list',
                                            'attribs.target_type:work',
                                            'relation',
                                            'direction.text:backward',
                                            'ordering_key',
                                            'text']
                                        parse_result = parse_data(release_id, response, [], *match_tree)
                                        if self.INFO:
                                            write_log(release_id, 'info', 'multi-works - ordering key for id %s is %s', idx,
                                                      parse_result)
                                        if parse_result and parse_result[0].isdigit(
                                        ):
                                            key = int(parse_result[0])
                                            self.parts[wid]['order'][idx] = key

                            parentIds = parentList[0]
                            parents = parentList[1]
                            if self.INFO:
                                write_log(release_id, 'info', 'Parents - ids: %s, names: %s', parentIds, parents)
                            # de-dup parent ids before we start
                            parentIds = list(
                                collections.OrderedDict.fromkeys(parentIds))
                            if parentIds:
                                if wid in self.works_cache:
                                    # Make sure we haven't done this relationship before, perhaps for another album
                                    if set(self.works_cache[wid]) != set(parentIds):
                                        prev_ids = tuple(self.works_cache[wid])
                                        prev_name = self.parts[prev_ids]['name']
                                        self.works_cache[wid] = add_list_uniquely(
                                            self.works_cache[wid], parentIds)
                                        self.parts[wid]['parent'] = add_list_uniquely(
                                            self.parts[wid]['parent'], parentIds)
                                        index = self.work_listing[album].index(
                                            prev_ids)
                                        new_id_list = add_list_uniquely(
                                            list(prev_ids), parentIds)
                                        new_ids = tuple(new_id_list)
                                        self.work_listing[album][index] = new_ids
                                        self.parts[new_ids] = self.parts[prev_ids]
                                        del self.parts[prev_ids]
                                        self.parts[new_ids]['name'] = add_list_uniquely(
                                            prev_name, parents)
                                        parentIds = new_id_list
                                else:
                                    self.works_cache[wid] = parentIds
                                    self.parts[wid]['parent'] = parentIds
                                    self.parts[tuple(parentIds)]['name'] = parents
                                    self.work_listing[album].append(
                                        tuple(parentIds))
                                # de-duplicate the parent names
                                self.parts[tuple(parentIds)]['name'] = list(
                                    collections.OrderedDict.fromkeys(self.parts[tuple(parentIds)]['name']))
                                # list(set()) won't work as need to retain
                                # order
                                # de-duplicate the parent ids also, otherwise they will be treated as a separate parent
                                # in the trackback structure
                                self.parts[wid]['parent'] = list(
                                    collections.OrderedDict.fromkeys(
                                        self.parts[wid]['parent']))
                                self.works_cache[wid] = list(
                                    collections.OrderedDict.fromkeys(
                                        self.works_cache[wid]))
                                if self.INFO:
                                    write_log(release_id, 'info',
                                              'Added parent ids to work_listing: %s, [Requests = %s]',
                                              parentIds, album._requests)
                                if self.INFO:
                                    write_log(release_id, 'info', 'work_listing after adding parents: %s',
                                              self.work_listing[album])
                                # the higher-level work might already be in cache
                                # from another album
                                if tuple(
                                        parentIds) in self.works_cache and self.USE_CACHE:
                                    not_in_cache = self.check_cache(
                                        track.metadata, album, track, tuple(parentIds), [])
                                    for workId_tuple in not_in_cache:
                                        new_queue.append((release_id, album, track, workId_tuple))

                                else:
                                    if not self.USE_CACHE:
                                        if tuple(parentIds) in self.works_cache:
                                            del self.works_cache[tuple(parentIds)]
                                    for parentId in parentIds:
                                        new_queue.append((release_id, album, track, (parentId,)))

                            else:
                                # so we remember we looked it up and found none
                                self.parts[wid]['no_parent'] = True
                                self.top_works[(track, album)]['workId'] = wid
                                if wid not in self.top[album]:
                                    self.top[album].append(wid)
                                if self.INFO:
                                    write_log(release_id, 'info', "TOP[album]: %s", self.top[album])
                        else:
                            # so we remember we looked it up and found none
                            self.parts[wid]['no_parent'] = True
                            self.top_works[(track, album)]['workId'] = wid
                            self.top[album].append(wid)

                if self.DEBUG or self.INFO:
                    write_log(release_id, 'debug', "End of tuple processing for workid %s in album %s, track %s,"
                                                   " requests remaining  = %s, new queue is %r",
                              workId, album, track, album._requests, new_queue)
                self.album_remove_request(release_id, album)
                for queued_item in new_queue:
                    if self.INFO:
                        write_log(release_id, 'info', 'Have a new queue: queued_item = %r', queued_item)
            write_log(release_id, 'debug',
                      'Penultimate end of work_process for %s (subject to parent lookups in "new_queue")', workId)
            for queued_item in new_queue:
                self.work_not_in_cache(queued_item[0], queued_item[1], queued_item[2], queued_item[3])
            write_log(release_id, 'debug',
                      'Ultimate end of work_process for %s', workId)
            if album._requests == 0:
                self.process_album(release_id, album)
                album._finalize_loading(None)
                close_log(release_id, 'works')





    def work_process_metadata(self, release_id, workId, wid, track, response):
        """
        Process XML node
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        NB release_id may be from a different album than the original, if works lookups are identical
        :param workId:
        :param wid:
        :param tuples:
        :param response:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "In work_process_metadata")
        if 'metadata' in response.children:
            if 'work' in response.metadata[0].children:
                all_tags = parse_data(release_id, response.metadata[0].work, [], 'tag_list', 'tag', 'name', 'text')
                self.parts[wid]['folks_genres'] = all_tags
                self.parts[wid]['worktype_genres'] = parse_data(release_id, response.metadata[0].work, [], 'attribs.type')
                key = parse_data(release_id, response.metadata[0].work, [], 'attribute_list', 'attribute',
                                 'attribs.type:Key', 'text')
                self.parts[wid]['key'] = key
                composed_begin_dates = year(
                    parse_data(release_id, response.metadata[0].work, [], 'relation_list', 'attribs.target_type:artist',
                               'relation', 'attribs.type:composer', 'begin', 'text'))
                composed_end_dates = year(
                    parse_data(release_id, response.metadata[0].work, [], 'relation_list', 'attribs.target_type:artist',
                               'relation', 'attribs.type:composer', 'end', 'text'))
                if composed_begin_dates == composed_end_dates:
                    composed_dates = composed_begin_dates
                else:
                    composed_dates = zip(composed_begin_dates, composed_end_dates)
                    composed_dates = [y + DATE_SEP + z for y, z in composed_dates]
                self.parts[wid]['composed_dates'] = composed_dates
                published_begin_dates = year(
                    parse_data(release_id, response.metadata[0].work, [], 'relation_list', 'attribs.target_type:label',
                               'relation', 'attribs.type:publishing', 'begin', 'text'))
                published_end_dates = year(
                    parse_data(release_id, response.metadata[0].work, [], 'relation_list', 'attribs.target_type:label',
                               'relation', 'attribs.type:publishing', 'end', 'text'))
                if published_begin_dates == published_end_dates:
                    published_dates = published_begin_dates
                else:
                    published_dates = zip(published_begin_dates, published_end_dates)
                    published_dates = [x + DATE_SEP + y for x, y in published_dates]
                self.parts[wid]['published_dates'] = published_dates

                premiered_begin_dates = year(
                    parse_data(release_id, response.metadata[0].work, [], 'relation_list', 'attribs.target_type:place',
                               'relation', 'attribs.type:premiere', 'begin', 'text'))
                premiered_end_dates = year(
                    parse_data(release_id, response.metadata[0].work, [], 'relation_list', 'attribs.target_type:place',
                               'relation', 'attribs.type:premiere', 'end', 'text'))
                if premiered_begin_dates == premiered_end_dates:
                    premiered_dates = premiered_begin_dates
                else:
                    premiered_dates = zip(premiered_begin_dates, premiered_end_dates)
                    premiered_dates = [x + DATE_SEP + y for x, y in premiered_dates]
                self.parts[wid]['premiered_dates'] = premiered_dates




                if 'artist_locale' in config.setting:
                    locale = config.setting["artist_locale"]
                    # NB this is the Picard code in /util
                    lang = locale.split("_")[0]
                    alias = parse_data(release_id, response.metadata[0].work, [], 'alias_list', 'alias',
                                       'attribs.locale:' + lang, 'attribs.primary:primary', 'text')
                    user_tags = parse_data(release_id, response.metadata[0].work, [], 'user_tag_list', 'user_tag',
                                           'name', 'text')
                    if config.setting['cwp_aliases_tags_user']:
                        tags = user_tags
                    else:
                        tags = all_tags
                    if alias:
                        self.parts[wid]['alias'] = self.parts[wid]['name'][:]
                        self.parts[wid]['tags'] = tags
                        for ind, w in enumerate(wid):
                            if w == workId:
                                # alias should be a one item list but...
                                self.parts[wid]['alias'][ind] = '; '.join(
                                    alias)
                relation_list = parse_data(release_id, response.metadata[0].work, [], 'relation_list')
                return self.work_process_relations(release_id, track, workId, wid, relation_list)

            else:
                if self.ERROR or self.INFO:
                    write_log(release_id, 'error', "%r: MusicBrainz work xml result not in correct format - %s",
                              workId, response)
                tm = track.metadata
                self.append_tag(release_id, tm, '~cwp_error',
                                '5. MusicBrainz work xml result not in correct format for work id: ' +
                                unicode(workId))
        return None

    def work_process_relations(self, release_id, track, workId, wid, relations):
        """
        Find the parents etc.
        NB track is just the last album/track for this work - used as being
        representative for options identification. If this is inconsistent (e.g. different collections
        option for albums with the same works) then the latest added track will over-ride others' settings).
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param track:
        :param workId:
        :param wid:
        :param relations:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "In work_process_relations. Relations--> %s", relations)
        if track:
            options = self.options[track]
        else:
            options = config.setting
        new_workIds = []
        new_works = []
        relation_attribute = parse_data(release_id, relations, [], 'attribs.target_type:work', 'relation',
                                        'attribs.type:parts', 'direction.text:backward', 'attribute_list', 'attribute',
                                        'text')
        if 'part of collection' not in relation_attribute or options['cwp_collections']:
            new_work_list = parse_data(release_id, relations, [], 'attribs.target_type:work', 'relation',
                                       'attribs.type:parts', 'direction.text:backward', 'work')
        else:
            new_work_list = []
        if new_work_list:
            new_workIds = parse_data(release_id, new_work_list, [], 'attribs', 'id')
            new_works = parse_data(release_id, new_work_list, [], 'title', 'text')
        else:
            arrangement_of = parse_data(release_id, relations, [], 'attribs.target_type:work', 'relation',
                                        'attribs.type:arrangement', 'direction.text:backward', 'work')
            if arrangement_of and options['cwp_arrangements']:
                new_workIds = parse_data(release_id, arrangement_of, [], 'attribs', 'id')
                new_works = parse_data(release_id, arrangement_of, [], 'title', 'text')
                self.parts[wid]['arrangement'] = True
            else:
                medley_of = parse_data(release_id, relations, [], 'attribs.target_type:work', 'relation',
                                       'attribs.type:medley', 'work')
                direction = parse_data(release_id, relations, [], 'attribs.target_type:work', 'relation',
                                       'attribs.type:medley', 'direction', 'text')
                if 'backward' not in direction:
                    if self.INFO:
                        write_log(release_id, 'info', 'Medley_of: %s', medley_of)
                    if medley_of and options['cwp_medley']:
                        medley_list = []
                        for medley_item in medley_of:
                            medley_list = medley_list + \
                                          parse_data(release_id, medley_item, [], 'title', 'text')
                            # (parse_data is a list...)
                            if self.INFO:
                                write_log(release_id, 'info', 'Medley_list: %s', medley_list)
                        self.parts[wid]['medley_list'] = medley_list

        if self.INFO:
            write_log(release_id, 'info', 'New works: ids: %s, names: %s', new_workIds, new_works)

        artists = get_artists(options, release_id, {}, relations, 'work')['artists']
        # artist_types = ['arranger', 'instrument arranger', 'orchestrator', 'composer', 'writer', 'lyricist',
        #                 'librettist', 'revised by', 'translator', 'reconstructed by', 'vocal arranger']

        if self.INFO:
            write_log(release_id, 'info', "ARTISTS %s", artists)

        workItems = (new_workIds, new_works)
        itemsFound = [workItems, artists]
        return itemsFound

    def album_add_request(self, release_id, album):
        """
        To keep track as to whether all lookups have been processed
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :return:
        """
        album._requests += 1
        write_log(release_id, 'debug', "Added album request - requests: %s", album._requests)

    def album_remove_request(self, release_id, album):
        """
        To keep track as to whether all lookups have been processed
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :return:
        """
        album._requests -= 1
        write_log(release_id, 'debug', "Removed album request - requests: %s", album._requests)

    ##################################################
    # SECTION 3 - Organise tracks and works in album #
    ##################################################

    def process_album(self, release_id, album):
        """
        Top routine to run end-of-album processes
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "PROCESS ALBUM %s", album)
        # populate the inverse hierarchy
        if self.INFO:
            write_log(release_id, 'info', "Cache: %s", self.works_cache)
        if self.INFO:
            write_log(release_id, 'info', "Work listing %s", self.work_listing)
        alias_tag_list = config.setting['cwp_aliases_tag_text'].split(',')
        for i, tag_item in enumerate(alias_tag_list):
            alias_tag_list[i] = tag_item.strip()
        for workId in self.work_listing[album]:
            if workId in self.parts:
                if self.INFO:
                    write_log(release_id, 'info', 'Processing workid: %s', workId)
                    write_log(release_id, 'info', 'self.work_listing[album]: %s', self.work_listing[album])
                if len(workId) > 1:
                    # fix the order of names using ordering keys gathered in
                    # work_process
                    if 'order' in self.parts[workId]:
                        seq = []
                        for idx in workId:
                            if idx in self.parts[workId]['order']:
                                seq.append(self.parts[workId]['order'][idx])
                            else:
                                # for the possibility of workids not part of
                                # the same parent and not all ordered
                                seq.append(999)
                        zipped_names = zip(self.parts[workId]['name'], seq)
                        sorted_tups = sorted(zipped_names, key=lambda x: x[1])
                        self.parts[workId]['name'] = [x[0]
                                                      for x in sorted_tups]
                # use aliases where appropriate
                # name is a list - need a string to test for Latin chars
                name_string = '; '.join(self.parts[workId]['name'])
                if config.setting['cwp_aliases']:
                    if config.setting['cwp_aliases_all'] or (
                        config.setting['cwp_aliases_greek'] and not only_roman_chars(name_string)) or (
                        'tags' in self.parts[workId] and any(
                            x in self.parts[workId]['tags'] for x in alias_tag_list)):
                        if 'alias' in self.parts[workId] and self.parts[workId]['alias']:
                            self.parts[workId]['name'] = self.parts[workId]['alias'][:]
                topId = None
                if self.INFO:
                    write_log(release_id, 'info', 'Works_cache: %s', self.works_cache)
                if workId in self.works_cache:
                    parentIds = tuple(self.works_cache[workId])
                    # for parentId in parentIds:
                    if self.DEBUG or self.INFO:
                        write_log(release_id, 'debug', "Create inverses: %s, %s", workId, parentIds)
                    if parentIds in self.partof[album]:
                        if workId not in self.partof[album][parentIds]:
                            self.partof[album][parentIds].append(workId)
                    else:
                        self.partof[album][parentIds] = [workId]
                    if self.INFO:
                        write_log(release_id, 'info', "Partof: %s", self.partof[album][parentIds])
                    if 'no_parent' in self.parts[parentIds]:
                        # to handle case if album includes works already in
                        # cache from a different album
                        if self.parts[parentIds]['no_parent']:
                            topId = parentIds
                else:
                    topId = workId
                if topId:
                    if album in self.top:
                        if topId not in self.top[album]:
                            self.top[album].append(topId)
                    else:
                        self.top[album] = [topId]
        # work out the full hierarchy and part levels
        height = 0
        if self.INFO:
            write_log(release_id, 'info', "TOP: %s, \nALBUM: %s, \nTOP[ALBUM]: %s", self.top, album,
                      self.top[album])
        if len(self.top[album]) > 1:
            single_work_album = 0
        else:
            single_work_album = 1
        for topId in self.top[album]:
            self.create_trackback(release_id, album, topId)
            if self.INFO:
                write_log(release_id, 'info', "Top id = %s, Name = %s", topId, self.parts[topId]['name'])

            if self.INFO:
                write_log(release_id, 'info', "Trackback before levels: %s", self.trackback[album][topId])
            if self.INFO:
                write_log(release_id, 'info', "Trackback before levels: %s", self.trackback[album][topId])
            work_part_levels = self.level_calc(release_id, self.trackback[album][topId], height)
            if self.INFO:
                write_log(release_id, 'info', "Trackback after levels: %s", self.trackback[album][topId])
            if self.INFO:
                write_log(release_id, 'info', "Trackback after levels: %s", self.trackback[album][topId])
            # determine the level which will be the principal 'work' level
            if work_part_levels >= 3:
                ref_level = work_part_levels - single_work_album
            else:
                ref_level = work_part_levels
            # extended metadata scheme won't display more than 3 work levels
            # ref_level = min(3, ref_level)
            ref_height = work_part_levels - ref_level
            top_info = {
                'levels': work_part_levels,
                'id': topId,
                'name': self.parts[topId]['name'],
                'single': single_work_album}
            # set the metadata in sequence defined by the work structure
            answer = self.process_trackback(release_id, album, self.trackback[album][topId], ref_height, top_info)
            if answer:
                tracks = answer[1]['track']
                if self.INFO:
                    write_log(release_id, 'info', "TRACKS: %s", tracks)
                # work_part_levels = self.trackback[album][topId]['depth']
                for track in tracks:
                    track_meta = track[0]
                    tm = track_meta.metadata
                    if '~cwp_workid_0' in tm:
                        workIds = interpret(tm['~cwp_workid_0'])
                        if workIds:
                            count = 0
                            self.process_work_artists(release_id, album, track_meta, workIds, tm, count)
                    title_work_levels = 0
                    if '~cwp_title_work_levels' in tm:
                        title_work_levels = int(tm['~cwp_title_work_levels'])
                    self.extend_metadata(release_id, top_info, track_meta, ref_height,
                                         title_work_levels)  # revise for new data
                    if track_meta not in self.tracks[album]:
                        self.tracks[album].append(track_meta)
                if self.DEBUG or self.INFO:
                    write_log(release_id, 'debug', "FINISHED TRACK PROCESSING FOR Top work id: %s", topId)
        # Need to redo the loop so that all album-wide tm is updated before
        # publishing
        for track in self.tracks[album]:
            self.publish_metadata(release_id, album, track)
        """
        The messages below are normally commented out as they get VERY long if there are a lot of albums loaded
        For extreme debugging, remove the comments and just run one or a few albums
        Do not forget to comment out again.
        """
        # if self.INFO:
        #     write_log(release_id, 'info', 'Self.parts: %s', self.parts)
        # if self.INFO:
        #     write_log(release_id, 'info', 'Self.trackback: %s', self.trackback)

        # tidy up
        self.trackback[album].clear()
        # Finally process the orphan tracks
        if album in self.orphan_tracks:
            for track in self.orphan_tracks[album]:
                self.publish_metadata(release_id, album, track)
        write_log(release_id, 'debug', "PROCESS ALBUM function complete")

    def create_trackback(self, release_id, album, parentId):
        """
        Create an inverse listing of the work-parent relationships
        :param release_id:
        :param album:
        :param parentId:
        :return: trackback for a given parentId
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Create trackback for %s", parentId)
        if parentId in self.partof[album]:  # NB parentId is a tuple
            for child in self.partof[album][parentId]:  # NB child is a tuple
                if child in self.partof[album]:
                    child_trackback = self.create_trackback(release_id, album, child)
                    self.append_trackback(release_id, album, parentId, child_trackback)
                else:
                    self.append_trackback(release_id, album, parentId, self.trackback[album][child])
            return self.trackback[album][parentId]
        else:
            return self.trackback[album][parentId]

    def append_trackback(self, release_id, album, parentId, child):
        """
        Recursive process to populate trackback
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :param parentId:
        :param child:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "In append_trackback...")
        if parentId in self.trackback[album]:  # NB parentId is a tuple
            if 'children' in self.trackback[album][parentId]:
                if child not in self.trackback[album][parentId]['children']:
                    if self.INFO:
                        write_log(release_id, 'info', "TRYING TO APPEND...")
                    self.trackback[album][parentId]['children'].append(child)
                    if self.INFO:
                        write_log(release_id, 'info', "...PARENT %s - ADDED %s as child", self.parts[parentId]['name'],
                                  child)
                else:
                    if self.INFO:
                        write_log(release_id, 'info', "Parent %s already has %s as child", parentId, child)
            else:
                self.trackback[album][parentId]['children'] = [child]
                if self.INFO:
                    write_log(release_id, 'info', "Existing PARENT %s - ADDED %s as child",
                              self.parts[parentId]['name'], child)
        else:
            self.trackback[album][parentId]['id'] = parentId
            self.trackback[album][parentId]['children'] = [child]
            if self.INFO:
                write_log(release_id, 'info', "New PARENT %s - ADDED %s as child", self.parts[parentId]['name'], child)
                write_log(release_id, 'info', "APPENDED TRACKBACK: %s", self.trackback[album][parentId])
        return self.trackback[album][parentId]

    def level_calc(self, release_id, trackback, height):
        """
        Recursive process to determine the max level for a work
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param trackback:
        :param height: number of levels above this one
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', 'In level_calc process')
        if 'children' not in trackback:
            if self.INFO:
                write_log(release_id, 'info', "Got to bottom")
            trackback['height'] = height
            trackback['depth'] = 0
            return 0
        else:
            trackback['height'] = height
            height += 1
            max_depth = 0
            for child in trackback['children']:
                if self.INFO:
                    write_log(release_id, 'info', "CHILD: %s", child)
                depth = self.level_calc(release_id, child, height) + 1
                if self.INFO:
                    write_log(release_id, 'info', "DEPTH: %s", depth)
                max_depth = max(depth, max_depth)
            trackback['depth'] = max_depth
            return max_depth

        ###########################################
        # SECTION 4 - Process tracks within album #
        ###########################################

    def process_trackback(self, release_id, album_req, trackback, ref_height, top_info):
        """
        Set work structure metadata & govern other metadata-setting processes
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album_req:
        :param trackback:
        :param ref_height:
        :param top_info:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "IN PROCESS_TRACKBACK. Trackback = %s", trackback)
        tracks = collections.defaultdict(dict)
        process_now = False
        if 'meta' in trackback:
            for track, album in trackback['meta']:
                if album_req == album:
                    process_now = True
        if process_now or 'children' not in trackback:
            if 'meta' in trackback and 'id' in trackback and 'depth' in trackback and 'height' in trackback:
                if self.INFO:
                    write_log(release_id, 'info', "Processing level 0")
                depth = trackback['depth']
                height = trackback['height']
                workId = tuple(trackback['id'])
                if depth != 0:
                    if 'children' in trackback:
                        child_response = self.process_trackback_children(release_id, album_req, trackback, ref_height,
                                                                         top_info, tracks)
                        tracks = child_response[1]
                    if self.INFO:
                        write_log(release_id, 'info',
                                  'Bottom level for this trackback is higher level elsewhere - adjusting levels')
                    depth = 0
                if self.INFO:
                    write_log(release_id, 'info', "WorkId %s", workId)
                if self.INFO:
                    write_log(release_id, 'info', "Work name %s", self.parts[workId]['name'])
                for track, album in trackback['meta']:
                    if album == album_req:
                        if self.INFO:
                            write_log(release_id, 'info', "Track: %s", track)
                        tm = track.metadata
                        if self.INFO:
                            write_log(release_id, 'info', "Track metadata = %s", tm)
                        tm['~cwp_workid_' + unicode(depth)] = workId
                        self.write_tags(release_id, track, tm, workId)
                        self.make_annotations(release_id, track, workId)
                        # strip leading and trailing spaces from work names
                        if isinstance(self.parts[workId]['name'], basestring):
                            worktemp = self.parts[workId]['name'].strip()
                        else:
                            for index, it in enumerate(
                                    self.parts[workId]['name']):
                                self.parts[workId]['name'][index] = it.strip()
                            worktemp = self.parts[workId]['name']
                        if isinstance(top_info['name'], basestring):
                            toptemp = top_info['name'].strip()
                        else:
                            for index, it in enumerate(top_info['name']):
                                top_info['name'][index] = it.strip()
                            toptemp = top_info['name']
                        tm['~cwp_work_' + unicode(depth)] = worktemp
                        tm['~cwp_part_levels'] = height
                        tm['~cwp_work_part_levels'] = top_info['levels']
                        tm['~cwp_workid_top'] = top_info['id']
                        tm['~cwp_work_top'] = toptemp
                        tm['~cwp_single_work_album'] = top_info['single']
                        if self.INFO:
                            write_log(release_id, 'info', "Track metadata = %s", tm)
                        if 'track' in tracks:
                            tracks['track'].append((track, height))
                        else:
                            tracks['track'] = [(track, height)]
                        if self.INFO:
                            write_log(release_id, 'info', "Tracks: %s", tracks)

                response = (workId, tracks)
                if self.DEBUG or self.INFO:
                    write_log(release_id, 'debug', "LEAVING PROCESS_TRACKBACK")
                if self.INFO:
                    write_log(release_id, 'info', "depth %s Response = %s", depth, response)
                return response
            else:
                return None
        else:
            response = self.process_trackback_children(release_id, album_req, trackback, ref_height, top_info, tracks)
            return response

    def process_trackback_children(self, release_id, album_req, trackback, ref_height, top_info, tracks):
        if 'id' in trackback and 'depth' in trackback and 'height' in trackback:
            if self.DEBUG or self.INFO:
                write_log(release_id, 'debug', 'In process_children_trackback for trackback %s', trackback)
            depth = trackback['depth']
            height = trackback['height']
            parentId = tuple(trackback['id'])
            parent = self.parts[parentId]['name']
            width = 0
            for child in trackback['children']:
                width += 1
                if self.INFO:
                    write_log(release_id, 'info', "child trackback = %s", child)
                answer = self.process_trackback(release_id, album_req, child, ref_height, top_info)
                if answer:
                    workId = answer[0]
                    child_tracks = answer[1]['track']
                    for track in child_tracks:
                        track_meta = track[0]
                        track_height = track[1]
                        part_level = track_height - height
                        if self.DEBUG or self.INFO:
                            write_log(release_id, 'debug', "Calling set metadata %s", (part_level, workId,
                                                                                       parentId, parent, track_meta))
                        self.set_metadata(release_id, part_level, workId, parentId, parent, track_meta)
                        if 'track' in tracks:
                            tracks['track'].append(
                                (track_meta, track_height))
                        else:
                            tracks['track'] = [(track_meta, track_height)]
                        tm = track_meta.metadata
                        # ~cwp_title if composer had to be removed
                        title = tm['~cwp_title'] or tm['title']
                        if 'title' in tracks:
                            tracks['title'].append(title)
                        else:
                            tracks['title'] = [title]
                        work = tm['~cwp_work_0']
                        if 'work' in tracks:
                            tracks['work'].append(work)
                        else:
                            tracks['work'] = [work]
                        if 'tracknumber' not in tm:
                            tm['tracknumber'] = 0
                        if 'tracknumber' in tracks:
                            tracks['tracknumber'].append(
                                int(tm['tracknumber']))
                        else:
                            tracks['tracknumber'] = [
                                int(tm['tracknumber'])]
            if tracks and 'track' in tracks:
                track = tracks['track'][0][0]
                # NB this will only be the first track of tracks, but its
                # options will be used for the structure
                self.derive_from_structure(release_id, top_info, tracks, height, depth, width, 'title')
                if self.options[track]["cwp_level0_works"]:
                    # replace hierarchical works with those from work_0 (for
                    # consistency)
                    self.derive_from_structure(release_id, top_info, tracks, height, depth, width, 'work')

                if self.INFO:
                    write_log(release_id, 'info', "Trackback result for %s = %s", parentId, tracks)
                response = parentId, tracks
                if self.DEBUG or self.INFO:
                    write_log(release_id, 'debug', "LEAVING PROCESS_CHILD_TRACKBACK depth %s Response = %s",
                              depth, response)
                return response
            else:
                return None
        else:
            return None

    def derive_from_structure(self, release_id, top_info, tracks, height, depth, width, name_type):
        """
        Derive title (or work level-0) components from MB hierarchical work structure
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param top_info:
         {'levels': work_part_levels,'id': topId,'name': self.parts[topId]['name'],'single': single_work_album}
        :param tracks:
         {'track':[(track1, height1), (track2, height2), ...], 'work': [work1, work2,...],
          'title': [title1, title2, ...], 'tracknumber': [tracknumber1, tracknumber2, ...]}
          where height is the number of levels in total in the branch for that track (i.e. height 1 => work_0 & work_1)
        :param height: number of levels above the current one
        :param depth: maximum number of levels
        :param width: number of siblings
        :param name_type: work or title
        :return:
        """
        allow_repeats = True
        if 'track' in tracks:
            track = tracks['track'][0][0]
            # NB this will only be the first track of tracks, but its
            # options will be used for the structure
            single_work_track = False  # default
            if self.DEBUG or self.INFO:
                write_log(release_id, 'debug', "Deriving info for %s from structure for tracks %s",
                          name_type, tracks['track'])
            if 'tracknumber' in tracks:
                sorted_tracknumbers = sorted(tracks['tracknumber'])
            else:
                sorted_tracknumbers = None
            if self.INFO:
                write_log(release_id, 'info', "SORTED TRACKNUMBERS: %s", sorted_tracknumbers)
            common_len = 0
            if name_type in tracks:
                meta_str = "_title" if name_type == 'title' else "_X0"
                name_list = tracks[name_type]
                if self.INFO:
                    write_log(release_id, 'info', "%s list %s", name_type, name_list)
                # only one track in this work so try and extract using colons
                if len(name_list) == 1:
                    single_work_track = True
                    track_height = tracks['track'][0][1]
                    if track_height - height > 0:  # part_level
                        if name_type == 'title':
                            if self.DEBUG or self.INFO:
                                write_log(release_id, 'debug',
                                          "Single track work. Deriving directly from title text: %s", track)
                            ti = name_list[0]
                            common_subset = self.derive_from_title(release_id, track, ti)[
                                0]
                        else:
                            common_subset = ""
                    else:
                        common_subset = name_list[0]
                    if self.INFO:
                        write_log(release_id, 'info', "%s is single-track work. common_subset is set to %s",
                                  tracks['track'][0][0], common_subset)
                    if common_subset:
                        common_len = len(common_subset)
                    else:
                        common_len = 0
                else:
                    compare = name_list[0].split()
                    for name in name_list:
                        lcs = longest_common_sequence(compare, name.split())
                        compare = lcs['sequence']
                        if not compare:
                            common_len = 0
                            break
                        if lcs['length'] > 0:
                            common_subset = " ".join(compare)
                            if self.INFO:
                                write_log(release_id, 'info',
                                          "Common subset from %ss at level %s, item name %s ..........", name_type,
                                          tracks['track'][0][1] - height, name)
                            if self.INFO:
                                write_log(release_id, 'info', "..........is %s", common_subset)
                            common_len = len(common_subset)

                if self.INFO:
                    write_log(release_id, 'info', "checked for common sequence - length is %s", common_len)
            for i, track_item in enumerate(tracks['track']):
                track_meta = track_item[0]
                tm = track_meta.metadata
                top_level = int(tm['~cwp_part_levels'])
                part_level = track_item[1] - height
                if common_len > 0:
                    if self.INFO:
                        write_log(release_id, 'info', "Use %s info for track: %s at level %s", name_type, track_meta,
                                  part_level)
                    name = tracks[name_type][i]
                    work = name[:common_len]
                    work = work.rstrip(":,.;- ")
                    if self.options[track]["cwp_removewords_p"]:
                        removewords = self.options[track]["cwp_removewords_p"].split(
                            ',')
                    else:
                        removewords = []
                    if self.INFO:
                        write_log(release_id, 'info', "Removewords (in %s) = %s", name_type, removewords)
                    for prefix in removewords:
                        prefix2 = unicode(prefix).lower().rstrip()
                        if prefix2[0] != " ":
                            prefix2 = " " + prefix2
                        if self.INFO:
                            write_log(release_id, 'info', "checking prefix %s", prefix2)
                        if work.lower().endswith(prefix2):
                            if len(prefix2) > 0:
                                work = work[:-len(prefix2)]
                                common_len = len(work)
                                work = work.rstrip(":,.;- ")
                    if self.INFO:
                        write_log(release_id, 'info', "work after prefix strip %s", work)
                        write_log(release_id, 'info', "Prefixes checked")

                    tm['~cwp' + meta_str + '_work_' +
                        unicode(part_level)] = work

                    if part_level > 0 and name_type == "work":
                        if self.INFO:
                            write_log(release_id, 'info', 'checking if %s is repeated name at part_level = %s', work,
                                      part_level)
                            write_log(release_id, 'info', 'lower work name is %s',
                                      tm['~cwp' + meta_str + '_work_' + unicode(part_level - 1)])
                        # fill in missing names caused by no common string at lower levels
                        # count the missing levels and push the current name
                        # down to the lowest missing level
                        missing_levels = 0
                        fill_level = part_level - 1
                        while '~cwp' + meta_str + '_work_' + \
                                unicode(fill_level) not in tm:
                            missing_levels += 1
                            fill_level -= 1
                            if fill_level < 0:
                                break
                        if self.INFO:
                            write_log(release_id, 'info', 'there is/are %s missing level(s)', missing_levels)
                        if missing_levels > 0:
                            allow_repeats = True
                        for lev in range(
                                part_level - missing_levels, part_level):

                            if lev > 0:  # not filled_lowest and lev > 0:
                                tm['~cwp' + meta_str +
                                    '_work_' + unicode(lev)] = work
                                tm['~cwp' +
                                   meta_str +
                                   '_part_' +
                                   unicode(lev -
                                           1)] = self.strip_parent_from_work(release_id, tm['~cwp' +
                                                                                            meta_str +
                                                                                            '_work_' +
                                                                                            unicode(lev -
                                                                                                    1)], tm['~cwp' +
                                                                                                            meta_str +
                                                                                                            '_work_' +
                                                                                                            unicode(
                                                                                                                lev)],
                                                                             lev -
                                                                             1, False)[0]
                            else:
                                tm['~cwp' +
                                   meta_str +
                                   '_work_' +
                                   unicode(lev)] = tm['~cwp_work_' +
                                                      unicode(lev)]

                        if missing_levels > 0 and self.INFO:
                            write_log(release_id, 'info', 'lower work name is now %s',
                                      tm['~cwp' + meta_str + '_work_' + unicode(part_level - 1)])
                        # now fix the repeated work name at this level
                        if work == tm['~cwp' + meta_str + '_work_' +
                                    unicode(part_level - 1)] and not allow_repeats:
                            tm['~cwp' +
                               meta_str +
                               '_work_' +
                               unicode(part_level)] = tm['~cwp_work_' +
                                                         unicode(part_level)]
                            self.level0_warn(release_id, tm, part_level)
                        tm['~cwp' +
                            meta_str + '_part_' +
                            unicode(part_level - 1)] = \
                                self.strip_parent_from_work(release_id, tm[
                                    '~cwp' + meta_str + '_work_' +
                                    unicode(part_level - 1)], tm[
                                                                '~cwp' + meta_str + '_work_' +
                                                                unicode(part_level)], part_level - 1, False)[0]

                    if part_level == 1:
                        movt = name[common_len:].strip().lstrip(":,.;- ")
                        if self.INFO:
                            write_log(release_id, 'info', "%s - movt = %s", name_type, movt)
                        tm['~cwp' + meta_str + '_part_0'] = movt
                    if self.INFO:
                        write_log(release_id, 'info', "%s Work part_level = %s", name_type, part_level)
                    if name_type == 'title':
                        if '~cwp_title_work_' + unicode(part_level - 1) in tm and tm['~cwp_title_work_' + unicode(
                                part_level)] == tm['~cwp_title_work_' + unicode(part_level - 1)] and width == 1:
                            pass  # don't count higher part-levels which are not distinct from lower ones
                                  #  when the parent work has only one child
                        else:
                            tm['~cwp_title_work_levels'] = depth
                            tm['~cwp_title_part_levels'] = part_level
                    if self.INFO:
                        write_log(release_id, 'info', "Set new metadata for %s OK", name_type)
                else:  # (no common substring at this level)
                    if name_type == 'work':
                        if self.INFO:
                            write_log(release_id, 'info',
                                      'single track work - indicator = %s. track = %s, part_level = %s, top_level = %s',
                                      single_work_track, track_item, part_level, top_level)
                        if part_level >= top_level:  # so it won't be covered by top-down action
                            for level in range(
                                    0, part_level + 1):  # fill in the missing work names from the canonical list
                                if '~cwp' + meta_str + '_work_' + \
                                        unicode(level) not in tm:
                                    tm['~cwp' +
                                       meta_str +
                                       '_work_' +
                                       unicode(level)] = tm['~cwp_work_' +
                                                            unicode(level)]
                                    if level > 0:
                                        self.level0_warn(release_id, tm, level)
                                if '~cwp' + meta_str + '_part_' + \
                                        unicode(level) not in tm and '~cwp_part_' + unicode(level) in tm:
                                    tm['~cwp' +
                                       meta_str +
                                       '_part_' +
                                       unicode(level)] = tm['~cwp_part_' +
                                                            unicode(level)]
                                    if level > 0:
                                        self.level0_warn(release_id, tm, level)

                # set movement number
                if name_type == 'title':  # so we only do it once
                    if part_level == 1:
                        if sorted_tracknumbers:
                            curr_num = tracks['tracknumber'][i]
                            posn = sorted_tracknumbers.index(curr_num) + 1
                            if self.INFO:
                                write_log(release_id, 'info', "posn %s", posn)
                        else:
                            posn = i + 1
                        tm['~cwp_movt_num'] = unicode(posn)

    def level0_warn(self, release_id, tm, level):
        """
        Issue warnings if inadequate level 0 data
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param tm:
        :param level:
        :return:
        """
        if self.WARNING or self.INFO:
            write_log(release_id, 'warning',
                      'Unable to use level 0 as work name source in level %s - using hierarchy instead', level)
            self.append_tag(release_id, tm, '~cwp_warning', '5. Unable to use level 0 as work name source in level ' +
                            unicode(level) +
                            ' - using hierarchy instead')

    def set_metadata(self, release_id, part_level, workId, parentId, parent, track):
        """
        Set the names of works and parts
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param part_level:
        :param workId:
        :param parentId:
        :param parent:
        :param track:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "SETTING METADATA FOR TRACK = %r, parent = %s, part_level = %s", track,
                      parent, part_level)
        tm = track.metadata
        if parentId:
            self.write_tags(release_id, track, tm, parentId)
            self.make_annotations(release_id, track, parentId)
            if 'annotations' in self.parts[workId]:
                work_annotations = self.parts[workId]['annotations']
                self.parts[workId]['stripped_annotations'] = work_annotations
            else:
                work_annotations = []
            if 'annotations' in self.parts[parentId]:
                parent_annotations = self.parts[parentId]['annotations']
            else:
                parent_annotations = []
            if parent_annotations:
                work_annotations = [z for z in work_annotations if z not in parent_annotations]
                self.parts[workId]['stripped_annotations'] = work_annotations


            tm['~cwp_workid_' + unicode(part_level)] = parentId
            tm['~cwp_work_' + unicode(part_level)] = parent
            # maybe more than one work name
            work = self.parts[workId]['name']
            if self.INFO:
                write_log(release_id, 'info', "Set work name to: %s", work)
            works = []
            # in case there is only one and it isn't in a list
            if isinstance(work, basestring):
                works.append(work)
            else:
                works = work[:]
            stripped_works = []
            for work in works:
                # partials (and often) arrangements will have the same name as
                # the "parent" and not be an extension
                if 'arrangement' in self.parts[workId] and self.parts[workId]['arrangement'] \
                        or 'partial' in self.parts[workId] and self.parts[workId]['partial']:
                    if not isinstance(parent, basestring):
                        # in case it is a list - make sure it is a string
                        parent = '; '.join(parent)
                    if not isinstance(work, basestring):
                        work = '; '.join(work)
                    diff = self.diff_pair(release_id, track, tm, parent, work)
                    if diff is None:
                        diff = ""
                    strip = [diff, parent]
                    # but don't leave name of arrangement blank unless it is
                    # virtually the same as the parent...
                    clean_work = re.sub("(?u)[\W]", ' ', work)
                    clean_work_list = clean_work.split()
                    extra_words = False
                    for work_word in clean_work_list:
                        if work_word not in parent:
                            extra_words = True
                            break
                    if extra_words:
                        if not diff and 'arrangement' in self.parts[
                                workId] and self.parts[workId]['arrangement']:
                            strip = self.strip_parent_from_work(release_id, work, parent, part_level, False)
                else:
                    extend = True
                    strip = self.strip_parent_from_work(release_id, work, parent, part_level, extend, parentId)
                stripped_works.append(strip[0])
                if self.INFO:
                    write_log(release_id, 'info', "Parent: %s", parent)
                # now == parent, after removing full_parent logic
                full_parent = strip[1]
                if full_parent != parent:
                    tm['~cwp_work_' +
                       unicode(part_level)] = full_parent.strip()
                    self.parts[parentId]['name'] = full_parent
                    if 'no_parent' in self.parts[parentId]:
                        if self.parts[parentId]['no_parent']:
                            tm['~cwp_work_top'] = full_parent.strip()
            tm['~cwp_part_' + unicode(part_level - 1)] = stripped_works
            self.parts[workId]['stripped_name'] = stripped_works
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "GOT TO END OF SET_METADATA")

    def write_tags(self, release_id, track, tm, workId):
        """
        write genre-realated tags from internal variables
        :param track:
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param tm: track metadata
        :param workId: MBID of current work
        :return: None - just writes tags
        """
        options = self.options[track]
        candidate_genres = []
        if options['cwp_genres_use_folks'] and 'folks_genres' in self.parts[workId]:
            candidate_genres += self.parts[workId]['folks_genres']
        if options['cwp_genres_use_worktype'] and 'worktype_genres' in self.parts[workId]:
            candidate_genres += self.parts[workId]['worktype_genres']
        self.append_tag(release_id, tm, '~cwp_candidate_genres', candidate_genres)
        self.append_tag(release_id, tm, '~cwp_keys', self.parts[workId]['key'])
        self.append_tag(release_id, tm, '~cwp_composed_dates', self.parts[workId]['composed_dates'])
        self.append_tag(release_id, tm, '~cwp_published_dates', self.parts[workId]['published_dates'])
        self.append_tag(release_id, tm, '~cwp_premiered_dates', self.parts[workId]['premiered_dates'])

    def make_annotations(self, release_id, track, wid):
        """
        create an 'annotations' entry in the 'parts' dict, as dictated by options, from dates and keys
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param track: the current track
        :param wid: the current work MBID
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Starting module %s", 'make_annotations')
        options = self.options[track]
        if options['cwp_workdate_include']:
            if options['cwp_workdate_source_composed'] and 'composed_dates' in self.parts[wid] and self.parts[wid]['composed_dates']:
                workdates = self.parts[wid]['composed_dates']
            elif options['cwp_workdate_source_published'] and 'published_dates' in self.parts[wid] and self.parts[wid]['published_dates']:
                workdates = self.parts[wid]['published_dates']
            elif options['cwp_workdate_source_premiered'] and 'premiered_dates' in self.parts[wid] and self.parts[wid]['premiered_dates']:
                workdates = self.parts[wid]['premiered_dates']
            else:
                workdates = []
        else:
            workdates = []
        if options['cwp_key_include'] and 'key' in self.parts[wid] and self.parts[wid]['key']:
            keys = self.parts[wid]['key']
        else:
            keys = []
        annotations = keys + workdates
        if annotations:
            self.parts[wid]['annotations'] = annotations
        else:
            if 'annotations' in self.parts[wid]:
                del self.parts[wid]['annotations']
        write_log(release_id, 'info', 'make annotations has set id %s on track %s with annotation %s', wid, track,
                  annotations)
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Ending module %s", 'make_annotations')

    def derive_from_title(self, release_id, track, title):
        """
        Attempt to parse title to get components
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param track:
        :param title:
        :return:
        """
        if self.INFO:
            write_log(release_id, 'info', "DERIVING METADATA FROM TITLE for track: %s", track)
        tm = track.metadata
        movt = title
        work = ""
        if '~cwp_part_levels' in tm:
            part_levels = int(tm['~cwp_part_levels'])
            if int(tm['~cwp_work_part_levels']
                   ) > 0:  # we have a work with movements
                colons = title.count(":")
                if colons > 0:
                    title_split = title.split(': ', 1)
                    title_rsplit = title.rsplit(': ', 1)
                    if part_levels >= colons:
                        work = title_rsplit[0]
                        movt = title_rsplit[1]
                    else:
                        work = title_split[0]
                        movt = title_split[1]
        if self.INFO:
            write_log(release_id, 'info', "Work %s, Movt %s", work, movt)
        return work, movt

    def process_work_artists(self, release_id, album, track, workIds, tm, count):
        """
        Carry out the artist processing that needs to be done in the PartLevels class
        as it requires XML lookups of the works
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :param track:
        :param workIds:
        :param tm:
        :param count:
        :return:
        """
        if not self.options[track]['classical_extra_artists']:
            if self.DEBUG or self.INFO:
                write_log(release_id, 'debug', 'Not processing work_artists as ExtraArtists not selected to be run')
            return None
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', 'In process_work_artists for track: %s, workIds: %s', track, workIds)
        if workIds in self.parts and 'arrangers' in self.parts[workIds]:
            if self.INFO:
                write_log(release_id, 'info', 'Arrangers = %s', self.parts[workIds]['arrangers'])
            set_work_artists(self, release_id, album, track, self.parts[workIds]['arrangers'], tm, count)
        if workIds in self.works_cache:
            count += 1
            self.process_work_artists(release_id, album, track, tuple(
                self.works_cache[workIds]), tm, count)

    #################################################
    # SECTION 5 - Extend work metadata using titles #
    #################################################

    def extend_metadata(self, release_id, top_info, track, ref_height, depth):
        """
        Combine MB work and title data according to user options
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param top_info:
        :param track:
        :param ref_height:
        :param depth:
        :return:
        """
        tm = track.metadata
        options = self.options[track]
        part_levels = int(tm['~cwp_part_levels'])
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug',
                      "Extending metadata for track: %s, ref_height: %s, depth: %s, part_levels: %s",
                      track, ref_height, depth, part_levels)
        if self.INFO:
            write_log(release_id, 'info', "Metadata = %s", tm)

        # previously: ref_height = work_part_levels - ref_level,
        # where this ref-level is the level for the top-named work
        ref_level = part_levels - ref_height
        # work_ref_level = work_part_levels - ref_height # not currently used

        # replace works and parts by those derived from the level 0 work, where
        # required, available and appropriate, but only use work names based on
        # level 0 text if it doesn't cause ambiguity

        # before embellishing with partial / arrangement etc
        vanilla_part = tm['~cwp_part_0']

        # Fix text for arrangements, partials and medleys (Done here so that
        # cache can be used)
        if options['cwp_arrangements'] and options["cwp_arrangements_text"]:
            for lev in range(
                    0,
                    ref_level):  # top level will not be an arrangement else there would be a higher level
                # needs to be a tuple to match
                if '~cwp_workid_' + unicode(lev) in tm:
                    tup_id = interpret(tm['~cwp_workid_' + unicode(lev)])
                    if 'arrangement' in self.parts[tup_id] and self.parts[tup_id]['arrangement']:
                        update_list = ['~cwp_work_', '~cwp_part_']
                        if options["cwp_level0_works"] and '~cwp_X0_work_' + \
                                unicode(lev) in tm:
                            update_list += ['~cwp_X0_work_', '~cwp_X0_part_']
                        for item in update_list:
                            tm[item + unicode(lev)] = options["cwp_arrangements_text"] + \
                                ' ' + tm[item + unicode(lev)]

        if options['cwp_partial'] and options["cwp_partial_text"]:
            if '~cwp_workid_0' in tm:
                work0_id = interpret(tm['~cwp_workid_0'])
                if 'partial' in self.parts[work0_id] and self.parts[work0_id]['partial']:
                    update_list = ['~cwp_work_0', '~cwp_part_0']
                    if options["cwp_level0_works"] and '~cwp_X0_work_0' in tm:
                        update_list += ['~cwp_X0_work_0', '~cwp_X0_part_0']
                    for item in update_list:
                        if len(work0_id) > 1 and isinstance(
                                tm[item], basestring):
                            meta_item = re.split(
                                '|'.join(self.SEPARATORS), (tm[item]))
                        else:
                            meta_item = tm[item]
                        if isinstance(meta_item, list):
                            for ind, w in enumerate(meta_item):
                                meta_item[ind] = options["cwp_partial_text"] + ' ' + w
                            tm[item] = meta_item
                        else:
                            tm[item] = options["cwp_partial_text"] + \
                                ' ' + tm[item]

        # fix "type 1" medley text
        if options['cwp_medley']:
            for lev in range(0, ref_level + 1):
                if '~cwp_workid_' + unicode(lev) in tm:
                    tup_id = interpret(tm['~cwp_workid_' + unicode(lev)])
                    if 'medley_list' in self.parts[tup_id]:
                        medley_list = self.parts[tup_id]['medley_list']
                        tm['~cwp_work_' + unicode(lev)] += " (" + options["cwp_medley_text"] + \
                            ' ' + ', '.join(medley_list) + ")"

        # add any annotations for dates and keys
        if options['cwp_workdate_include'] or options['cwp_key_include']:
            if options["cwp_titles"] and part_levels == 0:
                # ~cwp_title_work_0 will not have been set, but need it to hold any annotations
                tm['~cwp_title_work_0'] = tm['~cwp_title'] or tm['title']
            for lev in range(0, part_levels + 1):
                if '~cwp_workid_' + unicode(lev) in tm:
                    tup_id = interpret(tm['~cwp_workid_' + unicode(lev)])
                    if 'annotations' in self.parts[tup_id]:
                        write_log(release_id, 'info', 'in extend_metadata, annotations for id %s on track %s are %s',
                                  tup_id, track, self.parts[tup_id]['annotations'])
                        tm['~cwp_work_' + unicode(lev)] += " (" + ', '.join(self.parts[tup_id]['annotations']) + ")"
                        if options["cwp_level0_works"] and '~cwp_X0_work_' + unicode(lev) in tm:
                            tm['~cwp_X0_work_' + unicode(lev)] += " (" + ', '.join(self.parts[tup_id]['annotations']) + ")"
                        if options["cwp_titles"] and '~cwp_title_work_' + unicode(lev) in tm:
                                tm['~cwp_title_work_' + unicode(lev)] += " (" + ', '.join(self.parts[tup_id]['annotations']) + ")"
                        if lev < part_levels:
                            if 'stripped_annotations' in self.parts[tup_id]:
                                if self.parts[tup_id]['stripped_annotations']:
                                    tm['~cwp_part_' + unicode(lev)] += " (" + ', '.join(
                                        self.parts[tup_id]['stripped_annotations']) + ")"
                                    if options["cwp_level0_works"] and '~cwp_X0_part_' + unicode(lev) in tm:
                                        tm['~cwp_X0_part_' + unicode(lev)] += " (" + ', '.join(
                                            self.parts[tup_id]['stripped_annotations']) + ")"
                                    if options["cwp_titles"] and '~cwp_title_part_' + unicode(lev) in tm:
                                            tm['~cwp_title_part' + unicode(lev)] += " (" + ', '.join(
                                                self.parts[tup_id]['stripped_annotations']) + ")"


        part = []
        work = []
        for level in range(0, part_levels):
            part.append(tm['~cwp_part_' + unicode(level)])
            work.append(tm['~cwp_work_' + unicode(level)])
        work.append(tm['~cwp_work_' + unicode(part_levels)])

        # Use level_0-derived names if applicable
        if options["cwp_level0_works"]:
            for level in range(0, part_levels + 1):
                if '~cwp_X0_work_' + unicode(level) in tm:
                    work[level] = tm['~cwp_X0_work_' + unicode(level)]
                else:
                    if level != 0:
                        work[level] = ''
                if part and len(part) > level:
                    if '~cwp_X0_part_' + unicode(level) in tm:
                        part[level] = tm['~cwp_X0_part_' + unicode(level)]
                    else:
                        if level != 0:
                            part[level] = ''

        # set up group heading and part
        if part_levels > 0:
            groupheading = work[1]
            work_main = work[ref_level]
            inter_work = ""
            work_titles = tm['~cwp_title_work_' + unicode(ref_level)]
            if ref_level > 1:
                for r in range(1, ref_level):
                    if inter_work:
                        inter_work = ': ' + inter_work
                    inter_work = part[r] + inter_work
                groupheading = work[ref_level] + ':: ' + inter_work

        else:
            groupheading = work[0]
            work_main = groupheading
            inter_work = None
            work_titles = None

        if part:
            part_main = part[0]
        else:
            part_main = work[0]
        tm['~cwp_part'] = part_main

        # fix medley text for "type 2" medleys
        if self.parts[interpret(tm['~cwp_workid_0'])
                      ]['medley'] and options['cwp_medley']:
            if options["cwp_medley_text"]:
                groupheading = options["cwp_medley_text"] + ' ' + groupheading

        tm['~cwp_groupheading'] = groupheading
        tm['~cwp_work'] = work_main
        tm['~cwp_inter_work'] = inter_work
        tm['~cwp_title_work'] = work_titles
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Groupheading set to: %s", groupheading)
        # extend group heading from title metadata
        if groupheading:
            ext_groupheading = groupheading
            title_groupheading = None
            ext_work = work_main
            ext_inter_work = inter_work
            inter_title_work = ""

            if '~cwp_title_work_levels' in tm:

                title_depth = int(tm['~cwp_title_work_levels'])
                if self.INFO:
                    write_log(release_id, 'info', "Title_depth: %s", title_depth)
                diff_work = [""] * ref_level
                diff_part = [""] * ref_level
                title_tag = [""]
                tw_str_lower = 'x'  # to avoid errors, reset before used
                max_d = min(ref_level, title_depth) + 1
                for d in range(1, max_d):
                    tw_str = '~cwp_title_work_' + unicode(d)
                    if self.INFO:
                        write_log(release_id, 'info', "TW_STR = %s", tw_str)
                    if tw_str in tm:
                        title_tag.append(tm[tw_str])
                        title_work = title_tag[d]
                        work_main = work[d]
                        diff_work[d -
                                  1] = self.diff_pair(release_id, track, tm, work_main, title_work)
                        if d > 1 and tw_str_lower in tm:
                            title_part = self.strip_parent_from_work(release_id, tm[tw_str_lower], tm[tw_str], 0,
                                                                     False)[0].strip()
                            tm['~cwp_title_part_' +
                                unicode(d - 1)] = title_part
                            part_n = part[d - 1]
                            diff_part[d -
                                      1] = self.diff_pair(release_id, track, tm, part_n, title_part) or ""
                    else:
                        title_tag.append('')
                    tw_str_lower = tw_str
                if self.INFO:
                    write_log(release_id, 'info', "diff list for works: %s", diff_work)
                if self.INFO:
                    write_log(release_id, 'info', "diff list for parts: %s", diff_part)
                if not diff_work or len(diff_work) == 0:
                    if part_levels > 0:
                        ext_groupheading = groupheading
                else:
                    if self.DEBUG or self.INFO:
                        write_log(release_id, 'debug', "Now calc extended groupheading...")
                    if self.INFO:
                        write_log(release_id, 'info', "depth = %s, ref_level = %s, title_depth = %s", depth, ref_level,
                                  title_depth)
                    if self.INFO:
                        write_log(release_id, 'info', "diff_work = %s, diff_part = %s", diff_work, diff_part)
                    if part_levels > 0 and depth >= 1:
                        addn_work = []
                        addn_part = []
                        for stripped_work in diff_work:
                            if stripped_work:
                                if self.INFO:
                                    write_log(release_id, 'info', "Stripped work = %s", stripped_work)
                                addn_work.append(" {" + stripped_work + "}")
                            else:
                                addn_work.append("")
                        for stripped_part in diff_part:
                            if stripped_part and stripped_part != "":
                                if self.INFO:
                                    write_log(release_id, 'info', "Stripped part = %s", stripped_part)
                                addn_part.append(" {" + stripped_part + "}")
                            else:
                                addn_part.append("")
                        if self.INFO:
                            write_log(release_id, 'info', "addn_work = %s, addn_part = %s", addn_work, addn_part)
                        ext_groupheading = work[1] + addn_work[0]
                        ext_work = work[ref_level] + addn_work[ref_level - 1]
                        ext_inter_work = ""
                        inter_title_work = ""
                        title_groupheading = tm['~cwp_title_work_1']
                        if ref_level > 1:
                            for r in range(1, ref_level):
                                if ext_inter_work:
                                    ext_inter_work = ': ' + ext_inter_work
                                ext_inter_work = part[r] + \
                                    addn_part[r] + ext_inter_work
                            ext_groupheading = work[ref_level] + \
                                addn_work[ref_level - 1] + ':: ' + ext_inter_work
                        if title_depth > 1 and ref_level > 1:
                            for r in range(1, min(title_depth, ref_level)):
                                if inter_title_work:
                                    inter_title_work = ': ' + inter_title_work
                                inter_title_work = tm['~cwp_title_part_' +
                                                      unicode(r)] + inter_title_work
                            title_groupheading = tm['~cwp_title_work_' + unicode(
                                min(title_depth, ref_level))] + ':: ' + inter_title_work

                    else:
                        ext_groupheading = groupheading  # title will be in part
                        ext_work = work_main
                        ext_inter_work = inter_work
                        inter_title_work = ""

                    if self.DEBUG or self.INFO:
                        write_log(release_id, 'debug', ".... ext_groupheading done")

            if ext_groupheading:
                if self.INFO:
                    write_log(release_id, 'info', "EXTENDED GROUPHEADING: %s", ext_groupheading)
                tm['~cwp_extended_groupheading'] = ext_groupheading
                tm['~cwp_extended_work'] = ext_work
                if ext_inter_work:
                    tm['~cwp_extended_inter_work'] = ext_inter_work
                if inter_title_work:
                    tm['~cwp_inter_title_work'] = inter_title_work
                if title_groupheading:
                    tm['~cwp_title_groupheading'] = title_groupheading
                    if self.INFO:
                        write_log(release_id, 'info', "title_groupheading = %s", title_groupheading)
        # extend part from title metadata
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Now extend part...(part = %s)", part_main)
        if part_main:
            if '~cwp_title_part_0' in tm:
                movement = tm['~cwp_title_part_0']
            else:
                movement = tm['~cwp_title_part_0'] or tm['~cwp_title'] or tm['title']
            diff = self.diff_pair(release_id, track, tm, work[0], movement)
            # compare with the full work name, not the stripped one unless it
            # results in nothing
            if not diff and not vanilla_part:
                diff = self.diff_pair(release_id, track, tm, part_main, movement)
            if self.INFO:
                write_log(release_id, 'info', "DIFF PART - MOVT. ti =%s", diff)
            diff2 = diff
            if diff:
                if '~cwp_work_1' in tm:
                    if self.parts[interpret(tm['~cwp_workid_0'])]['partial']:
                        no_diff = False
                    else:
                        diff2 = self.diff_pair(release_id, track, tm, work[1], diff)
                        if diff2:
                            no_diff = False
                        else:
                            no_diff = True
                else:
                    no_diff = False
            else:
                no_diff = True
            if self.INFO:
                write_log(release_id, 'info', 'Set no_diff for %s = %s', tm['~cwp_workid_0'], no_diff)
                write_log(release_id, 'info', 'medley indicator for %s is %s', tm['~cwp_workid_0'],
                          self.parts[interpret(tm['~cwp_workid_0'])]['medley'])
            if self.parts[interpret(tm['~cwp_workid_0'])
                          ]['medley'] and options['cwp_medley']:
                no_diff = False
                if self.INFO:
                    write_log(release_id, 'info', 'setting no_diff = %s', no_diff)
            if no_diff:
                if part_levels > 0:
                    tm['~cwp_extended_part'] = part_main
                else:
                    tm['~cwp_extended_part'] = work[0]
                    if tm['~cwp_extended_groupheading']:
                        del tm['~cwp_extended_groupheading']
            else:
                if part_levels > 0:
                    stripped_movt = diff2.strip()
                    tm['~cwp_extended_part'] = part_main + \
                        " {" + stripped_movt + "}"
                else:
                    # title will be in part
                    tm['~cwp_extended_part'] = movement
        # remove unwanted groupheadings (needed them up to now for adding
        # extensions)
        if '~cwp_groupheading' in tm and tm['~cwp_groupheading'] == tm['~cwp_part']:
            del tm['~cwp_groupheading']
        if '~cwp_title_groupheading' in tm and tm['~cwp_title_groupheading'] == tm['~cwp_title_part']:
            del tm['~cwp_title_groupheading']
        # clean up groupheadings (may be stray separators if level 0  or title options used)
        if '~cwp_groupheading' in tm:
            tm['~cwp_groupheading'] = tm['~cwp_groupheading'].strip(
                ':').strip(
                options['cwp_single_work_sep']).strip(
                options['cwp_multi_work_sep'])
        if '~cwp_extended_groupheading' in tm:
           tm['~cwp_extended_groupheading'] =  tm['~cwp_extended_groupheading'].strip(
               ':').strip(
               options['cwp_single_work_sep']).strip(
               options['cwp_multi_work_sep'])
        if '~cwp_title_groupheading' in tm:
           tm['~cwp_title_groupheading'] =  tm['~cwp_title_groupheading'].strip(
               ':').strip(
               options['cwp_single_work_sep']).strip(
               options['cwp_multi_work_sep'])
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "....done")
        return None

    ##########################################################
    # SECTION 6- Write metadata to tags according to options #
    ##########################################################

    def publish_metadata(self, release_id, album, track):
        """
        Write out the metadata according to user options
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param album:
        :param track:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "IN PUBLISH METADATA for %s", track)
        options = self.options[track]
        tm = track.metadata
        tm['~cwp_version'] = PLUGIN_VERSION
        # album composers needed by map_tags (set in set_work_artists)
        if 'composer_lastnames' in self.album_artists[album]:
            last_names = seq_last_names(self, album)
            self.append_tag(release_id, tm, '~cea_album_composer_lastnames', last_names)

        if self.INFO:
            write_log(release_id, 'info', "Check options")
        if options["cwp_titles"]:
            if self.INFO:
                write_log(release_id, 'info', "titles")
            part = tm['~cwp_title_part_0'] or tm['~cwp_title_work_0']or tm['~cwp_title'] or tm['title']
            # for multi-level work display
            groupheading = tm['~cwp_title_groupheading'] or ""
            # for single-level work display
            work = tm['~cwp_title_work'] or ""
            inter_work = tm['~cwp_inter_title_work'] or ""
        elif options["cwp_works"]:
            if self.INFO:
                write_log(release_id, 'info', "works")
            part = tm['~cwp_part']
            groupheading = tm['~cwp_groupheading'] or ""
            work = tm['~cwp_work'] or ""
            inter_work = tm['~cwp_inter_work'] or ""
        else:
            # options["cwp_extended"]
            if self.INFO:
                write_log(release_id, 'info', "extended")
            part = tm['~cwp_extended_part']
            groupheading = tm['~cwp_extended_groupheading'] or ""
            work = tm['~cwp_extended_work'] or ""
            inter_work = tm['~cwp_extended_inter_work'] or ""
        if self.INFO:
            write_log(release_id, 'info', "Done options")
        p1 = re.compile(
            r'^\W*\bM{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})\b[\s|\.|:|,|;]',
            re.IGNORECASE)  # Matches Roman numerals with punctuation
        # Matches positive integers with punctuation
        p2 = re.compile(r'^\W*\d+[.):-]')
        movt = part
        for _ in range(
                0, 5):  # in case of multiple levels
            movt = p2.sub('', p1.sub('', movt)).strip()
        if self.INFO:
            write_log(release_id, 'info', "Done movt")
        movt_inc_tags = options["cwp_movt_tag_inc"].split(",")
        movt_inc_tags = [x.strip(' ') for x in movt_inc_tags]
        movt_exc_tags = options["cwp_movt_tag_exc"].split(",")
        movt_exc_tags = [x.strip(' ') for x in movt_exc_tags]
        movt_inc_1_tags = options["cwp_movt_tag_inc1"].split(",")
        movt_inc_1_tags = [x.strip(' ') for x in movt_inc_1_tags]
        movt_exc_1_tags = options["cwp_movt_tag_exc1"].split(",")
        movt_exc_1_tags = [x.strip(' ') for x in movt_exc_1_tags]
        movt_no_tags = options["cwp_movt_no_tag"].split(",")
        movt_no_tags = [x.strip(' ') for x in movt_no_tags]
        movt_no_sep = options["cwp_movt_no_sep"]
        gh_tags = options["cwp_work_tag_multi"].split(",")
        gh_tags = [x.strip(' ') for x in gh_tags]
        gh_sep = options["cwp_multi_work_sep"]
        work_tags = options["cwp_work_tag_single"].split(",")
        work_tags = [x.strip(' ') for x in work_tags]
        work_sep = options["cwp_single_work_sep"]
        top_tags = options["cwp_top_tag"].split(",")
        top_tags = [x.strip(' ') for x in top_tags]

        if self.INFO:
            write_log(release_id, 'info',
                      "Done splits. gh_tags: %s, work_tags: %s, movt_inc_tags: %s, movt_exc_tags: %s, movt_no_tags: %s",
                      gh_tags, work_tags, movt_inc_tags, movt_exc_tags, movt_no_tags)

        for tag in gh_tags + work_tags + movt_inc_tags + movt_exc_tags + movt_no_tags:
            tm[tag] = ""
        for tag in gh_tags:
            if tag in movt_inc_tags + movt_exc_tags + movt_no_tags:
                self.append_tag(release_id, tm, tag, groupheading, gh_sep)
            else:
                self.append_tag(release_id, tm, tag, groupheading)
        for tag in work_tags:
            if tag in movt_inc_1_tags + movt_exc_1_tags + movt_no_tags:
                self.append_tag(release_id, tm, tag, work, work_sep)
            else:
                self.append_tag(release_id, tm, tag, work)
            if '~cwp_part_levels' in tm and int(tm['~cwp_part_levels']) > 0:
                self.append_tag(release_id, tm, 'show work movement', '1')  # for iTunes
        for tag in top_tags:
            if '~cwp_work_top' in tm:
                self.append_tag(release_id, tm, tag, tm['~cwp_work_top'])

        for tag in movt_no_tags:
            self.append_tag(release_id, tm, tag, tm['~cwp_movt_num'])
            if tag in movt_inc_tags + movt_exc_tags:
                self.append_tag(release_id, tm, tag, movt_no_sep)

        for tag in movt_exc_tags:
            self.append_tag(release_id, tm, tag, movt)

        for tag in movt_inc_tags:
            self.append_tag(release_id, tm, tag, part)

        for tag in movt_inc_1_tags + movt_exc_1_tags:
            if tag in movt_inc_1_tags:
                pt = part
            else:
                pt = movt
            if inter_work and inter_work != "":
                if tag in movt_exc_tags + movt_inc_tags and tag != "":
                    if self.WARNING or self.INFO:
                        write_log(release_id, 'warning', "Tag %s will have multiple contents", tag)
                    self.append_tag(release_id, tm, '~cwp_warning', '6. Tag ' +
                                    tag +
                                    ' has multiple contents')
                self.append_tag(release_id, tm, tag, inter_work + work_sep + " " + pt)
            else:
                self.append_tag(release_id, tm, tag, pt)

        for tag in movt_exc_tags + movt_inc_tags + movt_exc_1_tags + movt_inc_1_tags:
            if tag in movt_no_tags:
                # i.e treat as one item, not multiple
                tm[tag] = "".join(re.split('|'.join(self.SEPARATORS), tm[tag]))

        # write "SongKong" tags
        if options['cwp_write_sk']:
            if self.DEBUG or self.INFO:
                write_log(release_id, 'debug', "Writing SongKong work tags")
            if '~cwp_part_levels' in tm:
                part_levels = int(tm['~cwp_part_levels'])
                for n in range(0, part_levels + 1):
                    if '~cwp_work_' + \
                            unicode(n) in tm and '~cwp_workid_' + unicode(n) in tm:
                        source = tm['~cwp_work_' + unicode(n)]
                        source_id = list(interpret(tm['~cwp_workid_' + unicode(n)]))
                        if n == 0:
                            self.append_tag(release_id, tm, 'musicbrainz_work_composition', source)
                            for source_id_item in source_id:
                                self.append_tag(release_id, tm, 'musicbrainz_work_composition_id', source_id_item)
                        if n == part_levels:
                            self.append_tag(release_id, tm, 'musicbrainz_work', source)
                            if 'musicbrainz_workid' in tm:
                                del tm['musicbrainz_workid']
                            # Delete the Picard version of this tag before
                            # replacing it with the SongKong version
                            for source_id_item in source_id:
                                self.append_tag(release_id, tm, 'musicbrainz_workid', source_id_item)
                        if n != 0 and n != part_levels:
                            self.append_tag(release_id, tm, 'musicbrainz_work_part_level' + unicode(n), source)
                            for source_id_item in source_id:
                                self.append_tag(release_id, tm, 'musicbrainz_work_part_level' + unicode(n) + '_id',
                                                source_id_item)

        # carry out tag mapping
        tm['~cea_works_complete'] = "Y"
        map_tags(options, release_id, album, tm)

        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Published metadata for %s", track)
        if options['cwp_options_tag'] != "":
            self.cwp_options = collections.defaultdict(
                lambda: collections.defaultdict(dict))

            for opt in plugin_options('workparts') + plugin_options('genres'):
                if 'name' in opt:
                    if 'value' in opt:
                        if options[opt['option']]:
                            self.cwp_options['Classical Extras']['Works options'][opt['name']] = opt['value']
                    else:
                        self.cwp_options['Classical Extras']['Works options'][opt['name']
                                                                              ] = options[opt['option']]

            if self.INFO:
                write_log(release_id, 'info', "Options %s", self.cwp_options)
            if options['ce_version_tag'] and options['ce_version_tag'] != "":
                self.append_tag(release_id, tm, options['ce_version_tag'], unicode(
                    'Version ' + tm['~cwp_version'] + ' of Classical Extras'))
            if options['cwp_options_tag'] and options['cwp_options_tag'] != "":
                self.append_tag(release_id, tm, options['cwp_options_tag'] +
                                ':workparts_options', json.loads(
                    json.dumps(
                        self.cwp_options)))
        if self.ERROR and "~cwp_error" in tm:
            for error in str_to_list(tm['~cwp_error']):
                code = error[0]
                self.append_tag(release_id, tm, '001_errors:' + code, error)
        if self.WARNING and "~cwp_warning" in tm:
            for warning in str_to_list(tm['~cwp_warning']):
                wcode = warning[0]
            self.append_tag(release_id, tm, '002_warnings:' + wcode, warning)

    def append_tag(self, release_id, tm, tag, source, sep=None):
        """
        pass to main append routine
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param tm:
        :param tag:
        :param source:
        :param sep: separators may be used to split string into list on appending
        :return:
        """
        if self.INFO:
            write_log(release_id, 'info', "In append_tag (Work parts). tag = %s, source = %s, sep =%s", tag, source,
                      sep)
        append_tag(release_id, tm, tag, source, self.SEPARATORS)
        if self.INFO:
            write_log(release_id, 'info', "Appended. Resulting contents of tag: %s are: %s", tag, tm[tag])

    ################################################
    # SECTION 7 - Common string handling functions #
    ################################################

    def strip_parent_from_work(self, release_id, work, parent, part_level, extend, parentId=None):
        """
        Remove common text
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param work:
        :param parent:
        :param part_level:
        :param extend:
        :param parentId:
        :return:
        """
        # extend=True is used [ NO LONGER to find "full_parent" names] + (with parentId)
        #  to trigger recursion if unable to strip parent name from work
        # extend=False is used when this routine is called for other purposes
        # than strict work: parent relationships
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "STRIPPING HIGHER LEVEL WORK TEXT FROM PART NAMES")
        if not isinstance(parent, basestring):
            # in case it is a list - make sure it is a string
            parent = '; '.join(parent)
        if not isinstance(work, basestring):
            work = '; '.join(work)

        # replace any punctuation or numbers, with a space (to remove any
        # inconsistent punctuation and numbering) - (?u) specifies the
        # re.UNICODE flag in sub
        clean_parent = re.sub("(?u)[\W]", ' ', parent)
        # now allow the spaces to be filled with up to 2 non-letters
        pattern_parent = re.sub("\s", "\W{0,2}", clean_parent)
        if extend:
            pattern_parent = "(.*\s|^)(\W*" + \
                pattern_parent + "\w*)(\W*\s)(.*)"
        else:
            pattern_parent = "(.*\s|^)(\W*" + pattern_parent + "\w*\W?)(.*)"
        if self.INFO:
            write_log(release_id, 'info', "Pattern parent: %s, Work: %s", pattern_parent, work)
        p = re.compile(pattern_parent, re.IGNORECASE | re.UNICODE)
        m = p.search(work)
        if m:
            if self.INFO:
                write_log(release_id, 'info', "Matched...")
            if extend:
                if m.group(1):
                    stripped_work = m.group(1) + u'\u2026' + m.group(4)
                else:
                    stripped_work = m.group(4)
            else:
                if m.group(1):
                    stripped_work = m.group(1) + u'\u2026' + m.group(3)
                else:
                    stripped_work = m.group(3)
            # may not have a full work name in the parent (missing op. no.
            # etc.)
            # HOWEVER, this next section has been removed, because it can cause incorrect answers if lower level
                    # works are inconsistently named. Use of level_0 naming can achieve result better and
                    # We want top work to be MB-canonical, regardless
                    # Nevertheless, this code is left in comments in case it proves useful again
            # if m.group(3) != ": " and extend:
            #     # no. of colons is consistent with "work: part" structure
            #     if work.count(": ") >= part_level:
            #         split_work = work.split(': ', 1)
            #         stripped_work = split_work[1]
            #         full_parent = split_work[0]
            #         if len(full_parent) < len(
            #                 parent):  # don't shorten parent names! (in case colon is mis-placed)
            #             full_parent = parent
            #             stripped_work = m.group(4)
        else:
            if self.INFO:
                write_log(release_id, 'info', "No match...")

            if extend and parentId and parentId in self.works_cache:
                if self.INFO:
                    write_log(release_id, 'info', "Looking for match at next level up")
                grandparentIds = tuple(self.works_cache[parentId])
                grandparent = self.parts[grandparentIds]['name']
                stripped_work = self.strip_parent_from_work(release_id, work, grandparent, part_level, True,
                                                            grandparentIds)[0]

            else:
                stripped_work = work
        if extend and stripped_work == work:
            # try just stripping only the first portion
            words = re.compile(r"[\w]+|[\W]")
            parent_words = words.findall(parent)
            work_words = words.findall(work)
            common_dets = longest_common_sequence(parent_words, work_words)
            common_seq = common_dets['sequence']
            seq_length = common_dets['length']
            if self.INFO:
                write_log(release_id, 'info', 'Checking common sequence between parent and work. Longest sequence = %s',
                          common_seq)
            if seq_length > 0:  # Make sure it is non-trivial
                # self.strip_parent_from_work(work, common_seq, part_level, False)[0]
                stripped_work = ''.join(work_words[seq_length:]).lstrip(' :,-')
        if self.INFO:
            write_log(release_id, 'info', "Work: %s", work)
        if self.INFO:
            write_log(release_id, 'info', "Stripped work: %s", stripped_work)
        # Changed full_parent to parent after removal of 'extend' logic above
        return stripped_work, parent

    def diff_pair(self, release_id, track, tm, mb_item, title_item):
        """
        Removes common text from title item
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param track:
        :param tm:
        :param mb_item:
        :param title_item:
        :return: Reduced title item
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "Inside DIFF_PAIR")
        mb = mb_item.strip()
        if self.INFO:
            write_log(release_id, 'info', "mb = %s", mb)
        if self.INFO:
            write_log(release_id, 'info', "title_item = %s", title_item)
        if not mb:
            return None
        ti = title_item.strip(" :;-.,")
        if ti.count('"') == 1:
            ti = ti.strip('"')
        if ti.count("'") == 1:
            ti = ti.strip("'")
        if self.INFO:
            write_log(release_id, 'info', "ti (amended) = %s", ti)
        if not ti:
            return None
        p1 = re.compile(
            r'^\W*\bM{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})\b[\s|\.|:|,|;]',
            re.IGNORECASE)  # Matches Roman numerals with punctuation
        # Matches positive integers with punctuation
        p2 = re.compile(r'^\W*\d+[.):-]')
        # remove certain words from the comparison
        if self.options[track]["cwp_removewords_p"]:
            removewords = self.options[track]["cwp_removewords_p"].split(',')
        else:
            removewords = []
        if self.INFO:
            write_log(release_id, 'info', "Removewords = %s", removewords)
        # remove numbers, roman numerals, part etc and punctuation from the
        # start
        if self.INFO:
            write_log(release_id, 'info', "checking prefixes")
        for i in range(
                0, 5):  # in case of multiple levels
            mb = p2.sub('', p1.sub('', mb)).strip()
            ti = p2.sub('', p1.sub('', ti)).strip()
            for prefix in removewords:
                if prefix[0] != " ":
                    prefix2 = unicode(prefix).lower().lstrip()
                    if self.INFO:
                        write_log(release_id, 'info', "checking prefix %s", prefix2)
                    if mb.lower().startswith(prefix2):
                        mb = mb[len(prefix2):]
                    if ti.lower().startswith(prefix2):
                        ti = ti[len(prefix2):]
            mb = mb.strip()
            ti = ti.strip()
            if self.INFO:
                write_log(release_id, 'info', "pairs after prefix strip iteration %s. mb = %s, ti = %s", i, mb, ti)
        if self.INFO:
            write_log(release_id, 'info', "Prefixes checked")

        #  replacements
        strreps = self.options[track]["cwp_replacements"].split('/')
        replacements = []
        for rep in strreps:
            tupr = rep.strip(' ()').split(',')
            if len(tupr) == 2:
                for i, tr in enumerate(tupr):
                    tupr[i] = tr.strip("' ").strip('"')
                tupr = tuple(tupr)
                replacements.append(tupr)
            else:
                if self.ERROR or self.INFO:
                    write_log(release_id, 'error', 'Error in replacement format for replacement %s', rep)
                self.append_tag(release_id, tm, '~cwp_error', '6. Error in replacement format for replacement ' +
                                rep)
        if self.INFO:
            write_log(release_id, 'info', "Replacement: %s", replacements)

        #  synonyms
        strsyns = self.options[track]["cwp_synonyms"].split('/')
        synonyms = []
        for syn in strsyns:
            tup = syn.strip(' ()').split(',')
            if len(tup) == 2:
                for i, ts in enumerate(tup):
                    tup[i] = ts.strip("' ").strip('"')
                    if not tup[i]:
                        if self.ERROR or self.INFO:
                            write_log(release_id, 'error', 'Synonym entries must not be blank - error in %s', syn)
                        self.append_tag(release_id, tm, '~cwp_error',
                                        '7. Synonym entries must not be blank - error in ' +
                                        syn)
                        tup[i] = "**BAD**"
                    elif re.findall(r'[^\w|\&]+', tup[i], re.UNICODE):
                        if self.ERROR or self.INFO:
                            write_log(release_id, 'error',
                                      'Synonyms must be single words without punctuation - error in %s', syn)
                        self.append_tag(release_id, tm, '~cwp_error',
                                        '7. Synonyms must be single words without punctuation - error in ' +
                                        syn)
                        tup[i] = "**BAD**"
                if "**BAD**" in tup:
                    continue
                else:
                    tup = tuple(tup)
                    synonyms.append(tup)
            else:
                if self.ERROR or self.INFO:
                    write_log(release_id, 'error', 'Error in synonmym format for synonym %s', syn)
                self.append_tag(release_id, tm, '~cwp_error', '7. Error in synonym format for synonym ' +
                                syn)
        if self.INFO:
            write_log(release_id, 'info', "Synonyms: %s", synonyms)

        # fix replacements and synonyms
        for key, equiv in replacements:
            if self.INFO:
                write_log(release_id, 'info', "key %s, equiv %s", key, equiv)
            if key[0] == "!" and key[1] == "!" and key[-1] == "!" and key[-2] == "!":  # we have a reg ex inside {{ }}
                key_pattern = key[2:-2]
            else:
                esc_key = re.escape(key)
                key_pattern = '\\b' + esc_key + '\\b'
            ti = re.sub(key_pattern, equiv, ti)
            if self.INFO:
                write_log(release_id, 'info', "Replaced replacements, ti = %s", ti)
        # Replace Roman numerals as per synonyms
        ti_test = replace_roman_numerals(ti)
        mb_test = replace_roman_numerals(mb)
        if self.INFO:
            write_log(release_id, 'info', 'Replaced Roman numerals. mb_test = %s, ti_test = %s', mb_test, ti_test)
        for key, equiv in synonyms:
            if self.INFO:
                write_log(release_id, 'info', "key %s, equiv %s", key, equiv)
            # mark the equivalents so that they can be reversed later
            esc_equiv = re.escape(equiv)
            equiv_pattern = '\\b' + esc_equiv + '\\b'
            syno = self.EQ + equiv  # designating that it derived from the synonym
            equo = equiv + self.EQ  # designating that it derived from the equivalent
            esc_key = re.escape(key)
            key_pattern = '\\b' + esc_key + '\\b'
            mb_test = re.sub(
                equiv_pattern,
                equo,
                mb_test,
                re.IGNORECASE | re.UNICODE)
            ti_test = re.sub(
                equiv_pattern,
                equo,
                ti_test,
                re.IGNORECASE | re.UNICODE)
            mb_test = re.sub(key_pattern, syno, mb_test,
                             re.IGNORECASE | re.UNICODE)
            ti_test = re.sub(key_pattern, syno, ti_test,
                             re.IGNORECASE | re.UNICODE)
            # better than ti_test = ti_test.replace(key, equiv)
            if self.INFO:
                write_log(release_id, 'info', "Replaced synonyms mb_test = %s, ti_test = %s", mb_test, ti_test)

        # check if the title item is wholly part of the mb item

        if self.INFO:
            write_log(release_id, 'info', "Testing if ti in mb. ti_test = %s, mb_test = %s", ti_test, mb_test)
        nopunc_ti = self.boil(release_id, ti_test)
        if self.INFO:
            write_log(release_id, 'info', "nopunc_ti =%s", nopunc_ti)
        nopunc_mb = self.boil(release_id, mb_test)
        if self.INFO:
            write_log(release_id, 'info', "nopunc_mb =%s", nopunc_mb)
        ti_len = len(nopunc_ti)
        if self.INFO:
            write_log(release_id, 'info', "ti len %s", ti_len)
        sub_len = int(ti_len)
        if self.INFO:
            write_log(release_id, 'info', "sub len %s", sub_len)
        if self.INFO:
            write_log(release_id, 'info', "Initial test. nopunc_mb = %s, nopunc_ti = %s, sub_len = %s", nopunc_mb,
                      nopunc_ti, sub_len)
        if self.INFO:
            write_log(release_id, 'info', "test sub....")
        lcs = longest_common_substring(nopunc_mb, nopunc_ti)['string']
        if self.INFO:
            write_log(release_id, 'info', "Longest common substring is: %s. Sub_len is %s", lcs, sub_len)
        if len(lcs) >= sub_len:
            return None

        # try and strip the canonical item from the title item (only a full
        # strip affects the outcome)
        if len(nopunc_mb) > 0:
            ti_new = self.strip_parent_from_work(release_id, ti_test, mb_test, 0, False)[0]
            if ti_new == ti_test:
                mb_list = re.split(
                    r';\s|:\s|\.\s|\-\s',
                    mb_test,
                    self.options[track]["cwp_granularity"])
                if self.INFO:
                    write_log(release_id, 'info', "mb_list = %s", mb_list)
                if mb_list:
                    for mb_bit in mb_list:
                        ti_new = self.strip_parent_from_work(release_id, ti_new, mb_bit, 0, False)[0]
                        if self.INFO:
                            write_log(release_id, 'info', "MB_BIT: %s, TI_NEW: %s", mb_bit, ti_new)
            else:
                if len(ti_new) > 0:
                    return self.reverse_syn(release_id, ti_new, synonyms)
                else:
                    return None
            if len(ti_new) == 0:
                return None
        # return any significant new words in the title
        words = 0
        nonWords = [
            "a",
            "the",
            "in",
            "on",
            "at",
            "of",
            "after",
            "and",
            "de",
            "d'un",
            "d'une",
            "la",
            "le"]
        # TODO Parameterize this?
        if self.INFO:
            write_log(release_id, 'info', "Check before splitting: mb_test = %s, ti_test = %s", mb_test, ti_test)
        ti_list = re.findall(r"\b\w+?\b|\B\&\B", ti, re.UNICODE)
        # allow ampersands and non-latin characters as word characters
        ti_list_punc = re.findall(r"[^\w|\&]+", ti, re.UNICODE)
        ti_test_list = re.findall(r"\b\w+?\b|\B\&\B", ti_test, re.UNICODE)
        if ti_list_punc:
            if ti_list_punc[0][0] == ti[0]:
                # list begins with punc
                ti_list.insert(0, '')
                ti_test_list.insert(0, '')
        if len(ti_list_punc) < len(ti_list):
            ti_list_punc.append('')
        ti_zip_list = zip(ti_list, ti_list_punc)

        # len(ti_list) should be = len(ti_test_list) as only difference should
        # be synonyms which are each one word
        mb_list2 = re.findall(r"\b\w+?\b|\B\&\B", mb_test, re.UNICODE)
        for index, mb_bit2 in enumerate(mb_list2):
            mb_list2[index] = self.boil(release_id, mb_bit2)
            if self.INFO:
                write_log(release_id, 'info', "mb_list2[%s] = %s", index, mb_list2[index])
        ti_new = []
        ti_comp_list = []
        ti_rich_list = []
        i = 0
        for i, ti_bit_test in enumerate(ti_test_list):
            if i <= len(ti_list) - 1:
                ti_bit = ti_zip_list[i]
                # NB ti_bit is a tuple where the word (1st item) is grouped
                # with its following punctuation (2nd item)
            else:
                ti_bit = ('', '')
            if self.INFO:
                write_log(release_id, 'info', "i = %s, ti_bit_test = %s, ti_bit = %s", i, ti_bit_test, ti_bit)
            # Boolean to indicate whether ti_bit is a new word
            ti_rich_list.append((ti_bit, True))
            if not ti_bit_test or (
                    ti_bit_test and self.boil(release_id, ti_bit_test) in mb_list2):
                if ti_bit_test:
                    words += 1
                ti_rich_list[i] = (ti_bit, False)
            else:
                if ti_bit_test.lower() not in nonWords and re.findall(
                        r'\w', ti_bit[0], re.UNICODE):
                    ti_comp_list.append(ti_bit[0])
        if self.INFO:
            write_log(release_id, 'info', "words %s", words)
        if self.INFO:
            write_log(release_id, 'info', "ti_comp_list = %s", ti_comp_list)
        if self.INFO:
            write_log(release_id, 'info', "ti_rich_list before removing singletons = %s. length = %s", ti_rich_list,
                      len(ti_rich_list))
        s = 0
        index = 0
        change = ()
        for i, (t, n) in enumerate(ti_rich_list):
            if n:
                s += 1
                index = i
                change = t  # NB this is a tuple
        if s == 1:
            if 0 < index < len(ti_rich_list) - 1:
                # ignore singleton new words in middle of title
                ti_rich_list[index] = (change, False)
                s = 0
        if self.INFO:
            write_log(release_id, 'info', "ti_rich_list before gapping = %s. length = %s", ti_rich_list,
                      len(ti_rich_list))
        if s > 0:
            p = self.options[track]["cwp_proximity"]
            d = self.options[track]["cwp_proximity"] - \
                self.options[track]["cwp_end_proximity"]
            for i, (ti_bit, new) in enumerate(ti_rich_list):
                if not new:
                    if self.INFO:
                        write_log(release_id, 'info', "%s not new. p = %s", ti_bit, p)
                    if p > 0:
                        for j in range(0, p + 1):
                            if self.INFO:
                                write_log(release_id, 'info', "i = %s, j = %s", i, j)
                            if i + j < len(ti_rich_list):
                                if ti_rich_list[i + j][1]:
                                    if self.INFO:
                                        write_log(release_id, 'info', "Set to true..")
                                    ti_rich_list[i] = (ti_bit, True)
                                    if self.INFO:
                                        write_log(release_id, 'info', "...set OK")
                            else:
                                if j <= p - d:
                                    ti_rich_list[i] = (ti_bit, True)
                else:
                    p = self.options[track]["cwp_proximity"]
                if not ti_rich_list[i][1]:
                    p -= 1
        if self.INFO:
            write_log(release_id, 'info', "ti_rich_list after gapping = %s", ti_rich_list)
        nothing_new = True
        for (ti_bit, new) in ti_rich_list:
            if new:
                nothing_new = False
                new_prev = True
                break
        if nothing_new:
            return None
        else:
            new_prev = False
            for i, (ti_bit, new) in enumerate(ti_rich_list):
                if self.INFO:
                    write_log(release_id, 'info', "Create new for %s?", ti_bit)
                if new:
                    if self.INFO:
                        write_log(release_id, 'info', "Yes for %s", ti_bit)
                    if not new_prev:
                        if i > 0:
                            # check to see if the last char of the prev
                            # punctuation group needs to be added first
                            if len(ti_rich_list[i - 1][0][1]) > 1:
                                # i.e. ti_bit[1][-1] of previous loop
                                ti_new.append(ti_rich_list[i - 1][0][1][-1])
                    ti_new.append(ti_bit[0])
                    if len(ti_bit[1]) > 1:
                        if i < len(ti_rich_list) - 1:
                            if ti_rich_list[i + 1][1]:
                                ti_new.append(ti_bit[1])
                            else:
                                ti_new.append(ti_bit[1][:-1])
                        else:
                            ti_new.append(ti_bit[1])
                    else:
                        ti_new.append(ti_bit[1])
                    if self.INFO:
                        write_log(release_id, 'info', "appended %s. ti_new is now %s", ti_bit, ti_new)
                else:
                    if self.INFO:
                        write_log(release_id, 'info', "Not for %s", ti_bit)
                    if new != new_prev:
                        ti_new.append(u'\u2026 ')

                new_prev = new
        if ti_new:
            if self.INFO:
                write_log(release_id, 'info', "ti_new %s", ti_new)
            ti = ''.join(ti_new)
            if self.INFO:
                write_log(release_id, 'info', "New text from title = %s", ti)
        else:
            if self.INFO:
                write_log(release_id, 'info', "New text empty")
            return None
        # see if there is any significant difference between the strings
        if ti:
            nopunc_ti = self.boil(release_id, ti)
            nopunc_mb = self.boil(release_id, mb)
            ti_len = len(nopunc_ti)
            sub_len = ti_len * \
                float(self.options[track]["cwp_substring_match"]) / 100
            if self.INFO:
                write_log(release_id, 'info', "test sub....")
            lcs = longest_common_substring(nopunc_mb, nopunc_ti)['string']
            if self.INFO:
                write_log(release_id, 'info', "Longest common substring is: %s. Threshold length is %s", lcs, sub_len)
            if len(lcs) >= sub_len:
                return None
            if self.INFO:
                write_log(release_id, 'info', "...done, ti =%s", ti)
        # remove duplicate successive words (and remove first word of title
        # item if it duplicates last word of mb item)
        if ti:
            ti_list_new = re.split(' ', ti)
            ti_list_ref = ti_list_new
            ti_bit_prev = None
            for i, ti_bit in enumerate(ti_list_ref):
                if ti_bit != "...":

                    if i > 1:
                        if self.boil(release_id, ti_bit) == self.boil(release_id, ti_bit_prev):
                            dup = ti_list_new.pop(i)
                            if self.INFO:
                                write_log(release_id, 'info', "...removed dup %s", dup)

                ti_bit_prev = ti_bit

            if self.INFO:
                write_log(release_id, 'info', "1st word of ti = %s. Last word of mb = %s", ti_list_new[0], mb_list2[-1])
            if ti_list_new and mb_list2:
                if self.boil(release_id, ti_list_new[0]) == mb_list2[-1]:
                    if self.INFO:
                        write_log(release_id, 'info', "Removing 1st word from ti...")
                    first = ti_list_new.pop(0)
                    if self.INFO:
                        write_log(release_id, 'info', "...removed %s", first)
            else:
                return None
            if ti_list_new:
                if self.INFO:
                    write_log(release_id, 'info', "rejoin list %s", ti_list_new)
                ti = ' '.join(ti_list_new)
            else:
                return None
        # remove excess brackets and punctuation
        if ti:
            ti = ti.strip("!&.-:;, ")
            if ti.count('"') == 1:
                ti = ti.strip('"')
            if ti.count("'") == 1:
                ti = ti.strip("'")
            if self.INFO:
                write_log(release_id, 'info', "stripped punc ok. ti = %s", ti)
            if ti:
                if ti.count("\"") == 1:
                    ti = ti.strip("\"")
                if ti.count("\'") == 1:
                    ti = ti.strip("\'")
                if "(" in ti and ")" not in ti:
                    ti = ti.replace("(", "")
                if ")" in ti and "(" not in ti:
                    ti = ti.replace(")", "")
                if "[" in ti and "]" not in ti:
                    ti = ti.replace("[", "")
                if "]" in ti and "[" not in ti:
                    ti = ti.replace("]", "")
                if "{" in ti and "}" not in ti:
                    ti = ti.replace("{", "")
                if "}" in ti and "{" not in ti:
                    ti = ti.replace("}", "")
            if ti:
                match_chars = [("(", ")"), ("[", "]"), ("{", "}")]
                last = len(ti) - 1
                for char_pair in match_chars:
                    if char_pair[0] == ti[0] and char_pair[1] == ti[last]:
                        ti = ti.lstrip(char_pair[0]).rstrip(char_pair[1])
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "DIFF_PAIR is returning ti = %s", ti)
        if ti and len(ti) > 0:
            return self.reverse_syn(release_id, ti, synonyms)
        else:
            return None

    def reverse_syn(self, release_id, term, synonyms):
        """
        reverse any synonyms left in the tititle item
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param term: the title item
        :param synonyms: tuples
        :return: title item without synonyms
        """
        for key, equiv in synonyms:
            if self.INFO:
                write_log(release_id, 'info', "key %s, equiv %s", key, equiv)
            equiv = self.EQ + equiv
            esc_equiv = re.escape(equiv)
            equiv_pattern = '\\b' + esc_equiv + '\\b'
            term = re.sub(equiv_pattern, key, term)
            term = term.replace(self.EQ, '')
        return term

    def boil(self, release_id, s):
        """
        Remove punctuation, spaces, capitals and accents for string comparisons
        :param release_id: name for log file - usually =musicbrainz_albumid
        unless called outside metadata processor
        :param s:
        :return:
        """
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "boiling %s", s)
        s = s.lower()
        if isinstance(s, str):
            s = s.decode('unicode_escape')
        s = s.replace(self.EQ.lower(), '')\
            .replace('sch', 'sh')\
            .replace(u'\xdf', 'ss')\
            .replace('sz', 'ss')\
            .replace(u'\u0153', 'oe')\
            .replace('oe', 'o')\
            .replace(u'\u00fc', 'ue')\
            .replace('ue', 'u')\
            .replace('ae', 'a')
        # first term above is to remove the markers used for synonyms, to
        # enable a true comparison
        punc = re.compile(r'\W*')
        s = ''.join(
            c for c in unicodedata.normalize(
                'NFD',
                s) if unicodedata.category(c) != 'Mn')
        boiled = punc.sub('', s).strip().lower().rstrip("s'")
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "boiled result = %s", boiled)
        return boiled

    # Remove certain keywords
    def remove_words(self, release_id, query, stopwords):
        if self.DEBUG or self.INFO:
            write_log(release_id, 'debug', "INSIDE REMOVE_WORDS")
        querywords = query.split()
        resultwords = []
        for word in querywords:
            if word.lower() not in stopwords:
                resultwords.append(word)
        return ' '.join(resultwords)



################
# OPTIONS PAGE #
################


class ClassicalExtrasOptionsPage(OptionsPage):
    NAME = "classical_extras"
    TITLE = "Classical Extras"
    PARENT = "plugins"
    opts = plugin_options('artists') + plugin_options('tag') +\
           plugin_options('workparts') + plugin_options('genres') + plugin_options('other')

    options = []
    # custom logging for non-album-related messages is written to startup.log
    for opt in opts:
        if 'type' in opt:
            if 'default' in opt:
                default = opt['default']
            else:
                default = ""
            if opt['type'] == 'Boolean':
                options.append(BoolOption("setting", opt['option'], default))
            elif opt['type'] == 'Text' or opt['type'] == 'Combo' or opt['type'] == 'PlainText':
                options.append(TextOption("setting", opt['option'], default))
            elif opt['type'] == 'Integer':
                options.append(IntOption("setting", opt['option'], default))
            else:
                write_log("session", 'error', "Error in setting options for option = %s", opt['option'])

    def __init__(self, parent=None):
        super(ClassicalExtrasOptionsPage, self).__init__(parent)
        self.ui = Ui_ClassicalExtrasOptionsPage()
        self.ui.setupUi(self)

    def load(self):
        """
        Load the options - NB all options are set in plugin_options, so this just parses that
        :return:
        """
        opts = plugin_options('artists') + plugin_options('tag') + \
               plugin_options('workparts') + plugin_options('genres') + plugin_options('other')

        # To force a toggle so that signal given
        toggle_list = ['use_cwp',
                       'use_cea',
                       'cea_override',
                       'cwp_override',
                       'cea_ra_use',
                       'cea_split_lyrics',
                       'cwp_partial',
                       'cwp_arrangements',
                       'cwp_medley',
                       'cwp_use_muso_refdb',]
        # count = 0
        for opt in opts:
            if opt['option'] == 'classical_work_parts':
                ui_name = 'use_cwp'
            elif opt['option'] == 'classical_extra_artists':
                ui_name = 'use_cea'
            else:
                ui_name = opt['option']
            if ui_name in toggle_list:
                not_setting = not self.config.setting[opt['option']]
                self.ui.__dict__[ui_name].setChecked(not_setting)

            if opt['type'] == 'Boolean':
                self.ui.__dict__[ui_name].setChecked(
                    self.config.setting[opt['option']])
            elif opt['type'] == 'Text':
                self.ui.__dict__[ui_name].setText(
                    self.config.setting[opt['option']])
            elif opt['type'] == 'PlainText':
                self.ui.__dict__[ui_name].setPlainText(
                    self.config.setting[opt['option']])
            elif opt['type'] == 'Combo':
                self.ui.__dict__[ui_name].setEditText(
                    self.config.setting[opt['option']])
            elif opt['type'] == 'Integer':
                self.ui.__dict__[ui_name].setValue(
                    self.config.setting[opt['option']])
            else:
                write_log('session', 'error', "Error in loading options for option = %s", opt['option'])

    def save(self):
        opts = plugin_options('artists') + plugin_options('tag') + \
               plugin_options('workparts') + plugin_options('genres') + plugin_options('other')

        for opt in opts:
            if opt['option'] == 'classical_work_parts':
                ui_name = 'use_cwp'
            elif opt['option'] == 'classical_extra_artists':
                ui_name = 'use_cea'
            else:
                ui_name = opt['option']
            if opt['type'] == 'Boolean':
                self.config.setting[opt['option']] = self.ui.__dict__[
                    ui_name].isChecked()
            elif opt['type'] == 'Text':
                self.config.setting[opt['option']] = unicode(
                    self.ui.__dict__[ui_name].text())
            elif opt['type'] == 'PlainText':
                self.config.setting[opt['option']] = unicode(
                    self.ui.__dict__[ui_name].toPlainText())
            elif opt['type'] == 'Combo':
                self.config.setting[opt['option']] = unicode(
                    self.ui.__dict__[ui_name].currentText())
            elif opt['type'] == 'Integer':
                self.config.setting[opt['option']
                                    ] = self.ui.__dict__[ui_name].value()
            else:
                write_log('session', 'error', "Error in saving options for option = %s", opt['option'])


#################
# MAIN ROUTINE  #
#################

# set defaults for certain options that MUST be manually changed by the
# user each time they are to be over-ridden
config.setting['use_cache'] = True
config.setting['ce_options_overwrite'] = False
config.setting['track_ars'] = True
config.setting['release_ars'] = True
# custom logging for non-album-related messages is written to startup.log
write_log('session', 'basic', 'Loading ' + PLUGIN_NAME)
REF_DICT = get_references_from_file('session',
                                    config.setting['cwp_muso_path'], config.setting['cwp_muso_refdb'])
write_log('session', 'info', 'External references (Muso):')
write_log('session', 'info', REF_DICT)
COMPOSER_DICT = REF_DICT['composers']
if config.setting['cwp_muso_classical'] and not COMPOSER_DICT:
    write_log('session', 'error', 'No composer roster found')
for cd in COMPOSER_DICT:
    cd['lc_name'] = [c.lower() for c in cd['name']]
    cd['lc_sort'] = [c.lower() for c in cd['sort']]
PERIOD_DICT = REF_DICT['periods']
if (config.setting['cwp_muso_dates'] or config.setting['cwp_muso_periods']) and not PERIOD_DICT:
    write_log('session', 'error', 'No period map found')
GENRE_DICT = REF_DICT['genres']
if config.setting['cwp_muso_genres'] and not GENRE_DICT:
    write_log('session', 'error', 'No classical genre list found')
register_track_metadata_processor(PartLevels().add_work_info)
register_track_metadata_processor(ExtraArtists().add_artist_info)
register_options_page(ClassicalExtrasOptionsPage)
write_log('session', 'basic', 'Finished intialisation')
# config.setting['log_debug'] = False
# config.setting['log_info'] = False
