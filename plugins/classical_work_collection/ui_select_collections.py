# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'C:\Users\Mark\Documents\Mark's documents\Music\Picard\Classical Works Collection development\classical_work_collection\select_collections.ui'
#
# Created: Thu May 17 14:20:56 2018
#      by: PyQt4 UI code generator 4.10
#
# WARNING! All changes made in this file will be lost!

from PyQt4 import QtCore, QtGui

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    def _fromUtf8(s):
        return s

try:
    _encoding = QtGui.QApplication.UnicodeUTF8
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig, _encoding)
except AttributeError:
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig)

class Ui_CollectionsDialog(object):
    def setupUi(self, CollectionsDialog):
        CollectionsDialog.setObjectName(_fromUtf8("CollectionsDialog"))
        CollectionsDialog.resize(408, 334)
        self.buttonBox = QtGui.QDialogButtonBox(CollectionsDialog)
        self.buttonBox.setGeometry(QtCore.QRect(40, 280, 341, 32))
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtGui.QDialogButtonBox.Cancel|QtGui.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName(_fromUtf8("buttonBox"))
        self.groupBox = QtGui.QGroupBox(CollectionsDialog)
        self.groupBox.setGeometry(QtCore.QRect(0, 10, 401, 161))
        self.groupBox.setObjectName(_fromUtf8("groupBox"))
        self.collection_list = QtGui.QListWidget(self.groupBox)
        self.collection_list.setGeometry(QtCore.QRect(10, 20, 371, 101))
        self.collection_list.setSelectionMode(QtGui.QAbstractItemView.MultiSelection)
        self.collection_list.setObjectName(_fromUtf8("collection_list"))
        self.label = QtGui.QLabel(self.groupBox)
        self.label.setGeometry(QtCore.QRect(10, 130, 431, 16))
        self.label.setObjectName(_fromUtf8("label"))
        self.max_works = QtGui.QSpinBox(CollectionsDialog)
        self.max_works.setGeometry(QtCore.QRect(310, 170, 71, 22))
        self.max_works.setMinimum(1)
        self.max_works.setMaximum(400)
        self.max_works.setObjectName(_fromUtf8("max_works"))
        self.label_2 = QtGui.QLabel(CollectionsDialog)
        self.label_2.setGeometry(QtCore.QRect(20, 170, 281, 16))
        self.label_2.setObjectName(_fromUtf8("label_2"))
        self.label_3 = QtGui.QLabel(CollectionsDialog)
        self.label_3.setGeometry(QtCore.QRect(20, 200, 261, 16))
        self.label_3.setObjectName(_fromUtf8("label_3"))
        self.label_4 = QtGui.QLabel(CollectionsDialog)
        self.label_4.setGeometry(QtCore.QRect(20, 210, 291, 16))
        self.label_4.setObjectName(_fromUtf8("label_4"))
        self.provide_analysis = QtGui.QCheckBox(CollectionsDialog)
        self.provide_analysis.setGeometry(QtCore.QRect(20, 230, 361, 31))
        self.provide_analysis.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.provide_analysis.setObjectName(_fromUtf8("provide_analysis"))
        self.label_5 = QtGui.QLabel(CollectionsDialog)
        self.label_5.setGeometry(QtCore.QRect(20, 250, 371, 16))
        self.label_5.setObjectName(_fromUtf8("label_5"))
        self.label_7 = QtGui.QLabel(CollectionsDialog)
        self.label_7.setGeometry(QtCore.QRect(20, 180, 261, 16))
        self.label_7.setObjectName(_fromUtf8("label_7"))

        self.retranslateUi(CollectionsDialog)
        QtCore.QObject.connect(self.buttonBox, QtCore.SIGNAL(_fromUtf8("accepted()")), CollectionsDialog.accept)
        QtCore.QObject.connect(self.buttonBox, QtCore.SIGNAL(_fromUtf8("rejected()")), CollectionsDialog.reject)
        QtCore.QMetaObject.connectSlotsByName(CollectionsDialog)

    def retranslateUi(self, CollectionsDialog):
        CollectionsDialog.setWindowTitle(_translate("CollectionsDialog", "Dialog", None))
        self.groupBox.setTitle(_translate("CollectionsDialog", "Select collections:-", None))
        self.label.setText(_translate("CollectionsDialog", "Highlight the collections into which to add the works from the selected tracks", None))
        self.label_2.setText(_translate("CollectionsDialog", "Maximum number of works to be added at a time", None))
        self.label_3.setText(_translate("CollectionsDialog", "(multiple submissions will be generated automatically", None))
        self.label_4.setText(_translate("CollectionsDialog", "if the total number of works to be added exceeds this max)", None))
        self.provide_analysis.setText(_translate("CollectionsDialog", "Provide analysis of existing collection and new works before updating? ", None))
        self.label_5.setText(_translate("CollectionsDialog", "(Faster if unchecked, but less informative)", None))
        self.label_7.setText(_translate("CollectionsDialog", "More than 200 may result in \"URI too large\" error", None))

