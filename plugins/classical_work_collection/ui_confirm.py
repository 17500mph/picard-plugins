# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'C:\Users\Mark\Documents\Mark's documents\Music\Picard\Classical Works Collection development\classical_work_collection\confirm.ui'
#
# Created: Wed May 16 11:07:22 2018
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

class Ui_ConfirmDialog(object):
    def setupUi(self, ConfirmDialog):
        ConfirmDialog.setObjectName(_fromUtf8("ConfirmDialog"))
        ConfirmDialog.resize(440, 130)
        self.groupBox = QtGui.QGroupBox(ConfirmDialog)
        self.groupBox.setGeometry(QtCore.QRect(20, 20, 391, 71))
        self.groupBox.setObjectName(_fromUtf8("groupBox"))
        self.label = QtGui.QLabel(self.groupBox)
        self.label.setGeometry(QtCore.QRect(10, 30, 371, 16))
        self.label.setObjectName(_fromUtf8("label"))
        self.label_2 = QtGui.QLabel(self.groupBox)
        self.label_2.setGeometry(QtCore.QRect(10, 50, 381, 16))
        self.label_2.setObjectName(_fromUtf8("label_2"))
        self.buttonBox = QtGui.QDialogButtonBox(ConfirmDialog)
        self.buttonBox.setGeometry(QtCore.QRect(10, 90, 341, 32))
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtGui.QDialogButtonBox.Cancel|QtGui.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName(_fromUtf8("buttonBox"))

        self.retranslateUi(ConfirmDialog)
        QtCore.QObject.connect(self.buttonBox, QtCore.SIGNAL(_fromUtf8("accepted()")), ConfirmDialog.accept)
        QtCore.QObject.connect(self.buttonBox, QtCore.SIGNAL(_fromUtf8("rejected()")), ConfirmDialog.reject)
        QtCore.QMetaObject.connectSlotsByName(ConfirmDialog)

    def retranslateUi(self, ConfirmDialog):
        ConfirmDialog.setWindowTitle(_translate("ConfirmDialog", "Dialog", None))
        self.groupBox.setTitle(_translate("ConfirmDialog", "Please confirm:-", None))
        self.label.setText(_translate("ConfirmDialog", "Adding xxxxxx works to the collection \"Collection\"", None))
        self.label_2.setText(_translate("ConfirmDialog", "All xxxxx selected works are already in the collection - no more will be added.", None))

