# -*- coding: utf-8 -*-
from __future__ import unicode_literals

PLUGIN_NAME = 'Enhanced Title Case'
PLUGIN_AUTHOR = 'Anthony Mario Diaz'
PLUGIN_DESCRIPTION = '''Do not replace certain words/abbreviations during Title Case Parsing.'''
PLUGIN_VERSION = '0.75'
PLUGIN_API_VERSIONS = ['2.0']

from PyQt5 import QtCore, QtGui, QtWidgets
from picard import config

import re, sys
from picard.album import Album
from picard.script import register_script_function
from picard.metadata import register_album_metadata_processor, register_track_metadata_processor
from picard.ui.options import register_options_page, OptionsPage
from picard.ui.itemviews import BaseAction, register_album_action
from picard.config import BoolOption, TextOption

class Ui_TitleCaseOptionsPage(object):

    def setupUi(self, TitleCaseOptionsPage):
        TitleCaseOptionsPage.setObjectName('TitleCaseOptionsPage')
        TitleCaseOptionsPage.resize(394, 300)
        self.verticalLayout = QtWidgets.QVBoxLayout(TitleCaseOptionsPage)
        self.verticalLayout.setObjectName('verticalLayout')
        self.groupBox = QtWidgets.QGroupBox(TitleCaseOptionsPage)
        self.groupBox.setObjectName('groupBox')
        self.vboxlayout = QtWidgets.QVBoxLayout(self.groupBox)
        self.vboxlayout.setObjectName('vboxlayout')
        self.titlecase_enable = QtWidgets.QCheckBox(self.groupBox)
        self.titlecase_enable.setObjectName('titlecase_enable')
        self.vboxlayout.addWidget(self.titlecase_enable)
        self.label = QtWidgets.QLabel(self.groupBox)
        self.label.setObjectName('label')
        self.vboxlayout.addWidget(self.label)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName('horizontalLayout')

        self.titlecase_keep_words = QtWidgets.QLineEdit(self.groupBox)
        self.titlecase_keep_words.setObjectName('titlecase_keep_words')
        self.horizontalLayout.addWidget(self.titlecase_keep_words)

        self.titlecase_small_words = QtWidgets.QLineEdit(self.groupBox)
        self.titlecase_small_words.setObjectName('titlecase_small_words')
        self.horizontalLayout.addWidget(self.titlecase_small_words)

        self.titlecase_artist_words = QtWidgets.QLineEdit(self.groupBox)
        self.titlecase_artist_words.setObjectName('titlecase_artist_words')
        self.horizontalLayout.addWidget(self.titlecase_artist_words)

        self.vboxlayout.addLayout(self.horizontalLayout)
        self.verticalLayout.addWidget(self.groupBox)
        spacerItem = QtWidgets.QSpacerItem(368, 187, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.retranslateUi(TitleCaseOptionsPage)
        QtCore.QMetaObject.connectSlotsByName(TitleCaseOptionsPage)

    def retranslateUi(self, TitleCaseOptionsPage):
        self.groupBox.setTitle(QtWidgets.QApplication.translate('TitleCaseOptionsPage', 'Enhanced Title Case'))
        self.titlecase_enable.setText(QtWidgets.QApplication.translate('TitleCaseOptionsPage',
                                                                       _('Ignore This Checkbox. Unused Placeholder.')))
        self.label.setText(QtWidgets.QApplication.translate('TitleCaseOptionsPage', _('Words to keep (comma-separated)')))
        self.titlecase_keep_words.setText(QtWidgets.QApplication.translate('TitleCaseOptionsPage', _('a|an|and')))

def keep_caps_specific_words(metadata):
    keep_words = config.setting['titlecase_keep_words']
    keep_words = [keep.word() for keep in keep_words.split(',')]
    for keep in keep_words:
        metadata.delete(keep)

class TitleCaseAction(BaseAction):
    NAME = _('Enhanced Title Case options...')

    def callback(self, objs):
        for album in objs:
            if isinstance(album, Album):
                keep_caps_specific_words(album.metadata)
                for track in album.tracks:
                    keep_caps_specific_words(track.metadata)
                    for file in track.linked_files:
                        track.update_file_metadata(file)
                album.update()

class TitleCaseOptionsPage(OptionsPage):
    NAME = 'titlecase'
    TITLE = 'Enhanced Title Case'
    PARENT = 'plugins'

    options = [
        BoolOption('setting', 'titlecase_enable', False),
        TextOption('setting', 'titlecase_keep_words', 'ENTER,COMMA,SEPARATED,TERMS'),
        TextOption('setting', 'titlecase_small_words', ''),
        TextOption('setting', 'titlecase_artist_words', 'The Beatles,The Who'),
    ]

    def __init__(self, parent=None):
        super(TitleCaseOptionsPage, self).__init__(parent)
        self.ui = Ui_TitleCaseOptionsPage()
        self.ui.setupUi(self)

    def load(self):
        self.ui.titlecase_keep_words.setText(config.setting['titlecase_keep_words'])
        self.ui.titlecase_small_words.setText(config.setting['titlecase_small_words'])
        self.ui.titlecase_artist_words.setText(config.setting['titlecase_artist_words'])
        self.ui.titlecase_enable.setChecked(config.setting['titlecase_enable'])

    def save(self):
        config.setting['titlecase_keep_words'] = str(self.ui.titlecase_keep_words.text())
        config.setting['titlecase_small_words'] = str(self.ui.titlecase_small_words.text())
        config.setting['titlecase_artist_words'] = str(self.ui.titlecase_artist_words.text())
        config.setting['titlecase_enable'] = self.ui.titlecase_enable.isChecked()

def keep_words_album_processor(tagger, metadata, release):
    if config.setting['titlecase_enable']:
        keep_caps_specific_words(metadata)

def keep_words_track_processor(tagger, metadata, track, release):
    if config.setting['titlecase_enable']:
        keep_caps_specific_words(metadata)

#  test strings
#  roller skating with us in the usa feat meco with the village people and snark  !!!
#  RollerSkating freaks eat ice cubs at the Drive-in with o'rielly and friends
#  the travelin prayers at the small stadium in the woods near o'reilly forest by the lake feat billy joel and the beatles with the who plus devo and abba mocking PhoolishPhloyd at the US festival in the usa.
#  empire strikes back (medley): darth vader / yoda's theme is too-loud and nOISy with the village people on t(o)p of all/this you want to feature AnOTeR bunch of idiots.


SMALL = config.setting['titlecase_small_words']
#  SMALL = 'a|an|and|as|at|but|by|en|for|feat|if|in|of|on|or|the|to|v\.?|via|vs\.?'
PUNCT = r"""!"“#$%&'‘()*+,\-–‒—―./:;?@[\\\]_`{|}~"""


SMALL_WORDS = re.compile(r'^(%s)$' % SMALL, re.I)
INLINE_PERIOD = re.compile(r'[a-z][.][a-z]', re.I)
UC_ELSEWHERE = re.compile(r'[%s]*?[a-zA-Z]+[A-Z]+?' % PUNCT)
CAPFIRST = re.compile(r"^[%s]*?([A-Za-z])" % PUNCT)
SMALL_FIRST = re.compile(r'^([%s]*)(%s)\b' % (PUNCT, SMALL), re.I)
SMALL_LAST = re.compile(r'\b(%s)[%s]?$' % (SMALL, PUNCT), re.I)
SMALL_AFTER_NUM = re.compile(r'(\d+\s+)(a|an|the)\b', re.I|re.U)
SUBPHRASE = re.compile(r'([:.;?!\-–‒—―][ ])(%s)' % SMALL)
APOS_SECOND = re.compile(r"^[dol]{1}['‘]{1}[a-z]+(?:['s]{2})?$", re.I)
ALL_CAPS = re.compile(r"^[A-Z\s%s]+$" % PUNCT)
UC_INITIALS = re.compile(r"^(?:[A-Z]{1}\.{1}|[A-Z]{1}\.{1}[A-Z]{1})+$")
MAC_MC = re.compile(r"^([Mm]c|MC)(\w.+)")

text_type = unicode if sys.version_info < (3,) else str

class Immutable(object):
    pass

class ImmutableString(text_type, Immutable):
    pass

class ImmutableBytes(bytes, Immutable):
    pass

def _mark_immutable(text):
    if isinstance(text, bytes):
        return ImmutableBytes(text)
    return ImmutableString(text)

def set_small_word_list(small=SMALL):
    global SMALL_WORDS
    global SMALL_FIRST
    global SMALL_LAST
    global SUBPHRASE
    SMALL_WORDS = re.compile(r'^(%s)$' % small, re.I)
    SMALL_FIRST = re.compile(r'^([%s]*)(%s)\b' % (PUNCT, small), re.I)
    SMALL_LAST = re.compile(r'\b(%s)[%s]?$' % (small, PUNCT), re.I)
    SUBPHRASE = re.compile(r'([:.;?!][ ])(%s)' % small)


def keepwords(word, **kwargs):
    if word.upper() in config.setting['titlecase_keep_words']:
        return word.upper()
#    if word in config.setting['titlecase_artist_words']:
#        return word


def apply_func(self, func):
    for name, values in list(self.rawitems()):
        if name not in PRESERVED_TAGS:
            self[name] = [func(value) for value in values]


def smart_title(s):
    return ' '.join(w if w.isupper() else w.capitalize() for w in s.split())


def func_titlecase(parser, text, callback=keepwords, small_first_last=True):
    """
    Original Perl version by: John Gruber http://daringfireball.net/ 10 May 2008
    Python version by Stuart Colville http://muffinresearch.co.uk
    License: http://www.opensource.org/licenses/mit-license.php
    """
    """
    Titlecase input text
    This filter changes all words to Title Caps, and attempts to be clever
    about *un*capitalizing SMALL words like a/an/the in the input.
    The list of "SMALL words" which are not capped comes from
    the New York Times Manual of Style, plus 'vs' and 'v'.
    """

    lines = re.split('[\r\n]+', text)
    processed = []
    for line in lines:
        all_caps = line.upper() == line
        words = re.split('[\t ]', line)
        tc_line = []
        for word in words:
            if callback:
                new_word = callback(word, all_caps=all_caps)
                if new_word:
                    # Address #22: If a callback has done something
                    # specific, leave this string alone from now on
                    tc_line.append(_mark_immutable(new_word))
                    continue

            if all_caps:
                if UC_INITIALS.match(word):
                    tc_line.append(word)
                    continue

            if APOS_SECOND.match(word):
                if len(word[0]) == 1 and word[0] not in 'aeiouAEIOU':
                    word = word[0].lower() + word[1] + word[2].upper() + word[3:]
                else:
                    word = word[0].upper() + word[1] + word[2].upper() + word[3:]
                tc_line.append(word)
                continue

            match = MAC_MC.match(word)
            if match:
                tc_line.append("%s%s" % (match.group(1).capitalize(),
                                         func_titlecase(None, match.group(2), callback, small_first_last)))
                continue

            if INLINE_PERIOD.search(word) or (not all_caps and UC_ELSEWHERE.match(word)):
                tc_line.append(word)
                continue
            if SMALL_WORDS.match(word):
                tc_line.append(word.lower())
                continue

            if "/" in word and "//" not in word:
                slashed = map(
                    lambda t: func_titlecase(None,t,callback,False),word.split('/'))
                tc_line.append("/".join(slashed))
                continue

            if '-' in word:
                hyphenated = map(
                    lambda t: func_titlecase(None,t,callback,small_first_last),
                    word.split('-')
                )
                tc_line.append("-".join(hyphenated))
                continue

            if all_caps:
                word = word.lower()

            # Just a normal word that needs to be capitalized
            tc_line.append(CAPFIRST.sub(lambda m: m.group(0).upper(), word))

        if small_first_last and tc_line:
            if not isinstance(tc_line[0], Immutable):
                tc_line[0] = SMALL_FIRST.sub(lambda m: '%s%s' % (
                    m.group(1),
                    m.group(2).capitalize()
                ), tc_line[0])

            if not isinstance(tc_line[-1], Immutable):
                tc_line[-1] = SMALL_LAST.sub(
                    lambda m: m.group(0).capitalize(), tc_line[-1]
                )

        result = " ".join(tc_line)

        result = SUBPHRASE.sub(lambda m: '%s%s' % (
            m.group(1),
            m.group(2).capitalize()
        ), result)

        processed.append(result)

    return "\n".join(processed)

register_album_metadata_processor(keep_words_album_processor)
register_track_metadata_processor(keep_words_track_processor)
register_album_action(TitleCaseAction())
register_options_page(TitleCaseOptionsPage)
register_script_function(func_titlecase, "titlecase")
