# encoding: utf-8

###########################################################################################################
#
#
# 	File Format Plugin
# 	Implementation for exporting fonts through the Export dialog
#
# 	Read the docs:
# 	https://github.com/schriftgestalt/GlyphsSDK/tree/master/Python%20Templates/File%20Format
#
# 	For help on the use of Xcode:
# 	https://github.com/schriftgestalt/GlyphsSDK/tree/master/Python%20Templates
#
#
###########################################################################################################

from __future__ import division, print_function, unicode_literals
import objc, os, tempfile, subprocess
from GlyphsApp import *
from GlyphsApp import GSScriptingHandler
from GlyphsApp.plugins import *
from Foundation import (
    NSMutableOrderedSet,
    NSClassFromString,
    NSZeroRect,
    NSMaxXEdge,
    NSArray,
    NSLog,
    NSAttributedString,
)
from AppKit import NSImageNameFolder, NSPopover, NSPopoverBehaviorTransient
import shutil

# Preference key names
ExportOutlineformatKey = "org_fontMake_exportOutlineformat"
ExportPathKey = "org_fontMake_exportPath"
UseExportPathKey = "org_fontMake_useExportPath"
AdditionalOptionsKey = "org_fontMake_additional_options"
ExportRecentExportPathsKey = "org_fontMake_recent_exportPaths"

OutlineFormatVariableTTF = 1
OutlineFormatVariableCFF = 2
OutlineFormatStaticCFF = 3
OutlineFormatStaticTTF = 4

outlineformatKeys = {
    OutlineFormatVariableTTF: ("variable",),
    OutlineFormatVariableCFF: ("variable-cff2",),
    OutlineFormatStaticCFF: ("otf", "-i"),
    OutlineFormatStaticTTF: ("ttf", "-i"),
}

GSAddParameterViewControllerClass = NSClassFromString("GSAddParameterViewController")


class GSAddOptionViewController(GSAddParameterViewControllerClass):
    def addParameter_(self, sender):
        newOptions = []
        for option in self.customParameterController().selectedObjects():
            name = option["identifier"]
            newOptions.append(name)
        if len(newOptions) == 0:
            return
        options = Glyphs.defaults[AdditionalOptionsKey]
        if options is None:
            options = ""
        options += " ".join(newOptions)
        Glyphs.defaults[AdditionalOptionsKey] = options


class FontMakeExport(FileFormatPlugin):

    # Definitions of IBOutlets

    # The NSView object from the User Interface. Keep this here!
    dialog = objc.IBOutlet()

    # Example variables. You may delete them
    variableTTFButton = objc.IBOutlet()
    variableCFFButton = objc.IBOutlet()
    staticCFFButton = objc.IBOutlet()
    staticTTFButton = objc.IBOutlet()
    recentExportPathsButton = objc.IBOutlet()
    additionalOptions = objc.IBOutlet()

    @objc.python_method
    def settings(self):
        self.name = Glyphs.localize({"en": "fontMake"})
        self.icon = "ExportIconTemplate"
        self.toolbarPosition = 100
        self._options = None  # lazy load when actually needed.
        # Load .nib dialog (with .extension)
        self.loadNib("IBdialog", __file__)

    @objc.python_method
    def start(self):

        # Init user preferences if not existent and set default value
        Glyphs.registerDefault(ExportOutlineformatKey, OutlineFormatVariableTTF)
        Glyphs.registerDefault(ExportPathKey, os.path.expanduser("~/Documents"))

        self.setupCheckboxes()
        self.setupRecentExportPathsButton()

    # Example function. You may delete it
    @objc.IBAction
    def setFileType_(self, sender):

        outlineFormat = sender.tag()
        Glyphs.intDefaults[ExportOutlineformatKey] = outlineFormat
        self.setupCheckboxes()

    def setupCheckboxes(self):
        outlineformat = Glyphs.intDefaults[ExportOutlineformatKey]

        self.variableTTFButton.setState_(outlineformat == OutlineFormatVariableTTF)
        self.variableTTFButton.setTag_(OutlineFormatVariableTTF)
        self.variableCFFButton.setState_(outlineformat == OutlineFormatVariableCFF)
        self.variableCFFButton.setTag_(OutlineFormatVariableCFF)
        self.staticCFFButton.setState_(outlineformat == OutlineFormatStaticCFF)
        self.staticCFFButton.setTag_(OutlineFormatStaticCFF)
        self.staticTTFButton.setState_(outlineformat == OutlineFormatStaticTTF)
        self.staticTTFButton.setTag_(OutlineFormatStaticTTF)

    @objc.python_method
    def setupRecentExportPathsButton(self):
        menu = self.recentExportPathsButton.menu()
        while len(menu.itemArray()) > 1:
            menu.removeItemAtIndex_(1)

        recentExportPaths = Glyphs.defaults[ExportRecentExportPathsKey]
        if recentExportPaths and len(recentExportPaths) > 0:
            folderImage = NSImage.imageNamed_(NSImageNameFolder)
            folderImage.setSize_(NSMakeSize(16, 16))

            for recentExportPath in recentExportPaths:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    recentExportPath.stringByStandardizingPath().stringByAbbreviatingWithTildeInPath(),
                    "setRecentExportPath:",
                    "",
                )
                item.setRepresentedObject_(recentExportPath)
                item.setImage_(folderImage)
                item.setTarget_(self)
                menu.addItem_(item)

            item = NSMenuItem.separatorItem()
            menu.addItem_(item)

            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Clear Recent", "clearRecent:", ""
            )
            item.setTarget_(self)
            menu.addItem_(item)

        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Update fontMake", "updateFontMake:", ""
        )
        item.setTarget_(self)
        menu.addItem_(item)

    @objc.python_method
    def tempPath(self, familyName):
        appSupportSubpath = GSGlyphsInfo.applicationSupportPath()
        tempPath = os.path.join(appSupportSubpath, "Temp", familyName)
        os.makedirs(tempPath, exist_ok=True)
        return tempPath

    @objc.python_method
    def venvPath(self):
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "venv")

    @objc.python_method
    def setUpEnviroment(self):
        venvPath = self.venvPath()
        venvPythonPath = os.path.join(venvPath, "bin/python3")
        if os.path.exists(venvPythonPath):
            return venvPythonPath

        scriptingHandler = GSScriptingHandler.sharedHandler()
        glyphsPythonPath = os.path.join(
            scriptingHandler.currentPythonPath(), "bin/python3"
        )
        print("__glyphsPythonPath", glyphsPythonPath)

        venvCommand = [glyphsPythonPath, "-m", "venv", venvPath]
        result = subprocess.run(venvCommand, capture_output=True, text=False)
        print("__result venv", result.returncode, result)

        venvPipPath = os.path.join(venvPath, "bin/pip3")
        pipCommand = [venvPipPath, "install", "fontmake[all]"]
        result = subprocess.run(pipCommand, capture_output=True, text=False)
        print("__result pip", result.returncode, result)

        return venvPythonPath

    def setRecentExportPath_(self, sender):
        exportPath = sender.representedObject()
        Glyphs.defaults[ExportPathKey] = exportPath

    def clearRecent_(self, sender):
        Glyphs.defaults[ExportRecentExportPathsKey] = None
        self.setupRecentExportPathsButton()

    def options(self):
        if self._options is None:
            NSLog("__path %@", os.path.join(os.path.dirname(__file__), "options.plist"))
            options = NSArray.arrayWithContentsOfFile_(
                os.path.join(os.path.dirname(__file__), "options.plist")
            )
            NSLog("__options %d", len(options))

            for option in options:
                text = option.get("text", None)
                if text:
                    text = NSAttributedString.attributedStringFromMarkdownString_(text)
                    option["text"] = text
            self._options = options
        return self._options

    def updateFontMake_(self, sender):
        venvPath = self.venvPath()
        if os.path.exists(venvPath):
            print(
                "Remove Venv folder:", venvPath
            )  # will be re-downloaded on next export
            shutil.rmtree(venvPath)

    @objc.IBAction
    def showAddOptionPopup_(self, sender):
        contentViewController = GSAddOptionViewController.new()
        contentViewController.setCustomParameters_(self.options())
        popover = NSPopover.new()
        popover.setBehavior_(NSPopoverBehaviorTransient)
        popover.setContentViewController_(contentViewController)
        popover.setDelegate_(contentViewController)

        popover.showRelativeToRect_ofView_preferredEdge_(NSZeroRect, sender, NSMaxXEdge)

    @objc.python_method
    def export(self, font):
        venvPythonPath = self.setUpEnviroment()
        if Glyphs.boolDefaults[UseExportPathKey]:
            exportPath = Glyphs.defaults[ExportPathKey]
        else:
            exportPath = GetFolder()

        if exportPath is None:
            return False, "No export path"

        tempFolder = self.tempPath(font.familyName)
        print("__tempFolder", tempFolder)
        tempFile = os.path.join(tempFolder, "font.glyphs")
        font.save(tempFile, makeCopy=True)

        outlineformat = Glyphs.intDefaults[ExportOutlineformatKey]
        outlineformatKey = outlineformatKeys[outlineformat]
        additionalOptions = Glyphs.defaults[AdditionalOptionsKey]
        print("__additionalOptions", additionalOptions)
        master_dir = os.path.join(tempFolder, "masters")

        arguments = [
            venvPythonPath,
            "-m",
            "fontmake",
            "--output-dir",
            exportPath,
            "--master-dir",
            os.path.join(exportPath, "masters"),
            "--instance-dir",
            os.path.join(exportPath, "instances"),
            "-g",
            tempFile,
            "-o",
            *outlineformatKey,
        ]
        if additionalOptions:
            additionalOptions = additionalOptions.split(" ")
            if len(additionalOptions) > 0:
                arguments.extend(additionalOptions)

        print("__arguments", arguments)
        result = subprocess.run(arguments, capture_output=True, text=True)
        print("__result", result.stdout, "\n", result.stderr)
        stderr = result.stderr

        if stderr is not None and len(stderr) > 0:
            lines = stderr.split("\n")
            errorLines = []
            for line in lines:
                if line.startswith("ERROR:") or "fontmake: Error:" in line:
                    errorLines.append(line)
            if len(errorLines) > 0:
                stderr = "\n".join(errorLines)
                return False, stderr

        return True, "OK"

    @objc.IBAction
    def openDoc_(self, sender):
        path = GetFolder()
        if path is not None:
            print("__path", path)
            Glyphs.defaults[ExportPathKey] = path

            recentExportPaths = Glyphs.defaults[ExportRecentExportPathsKey]
            if not recentExportPaths:
                recentExportPaths = []

            recentExportPathsSet = NSMutableOrderedSet.alloc().initWithArray_(
                recentExportPaths
            )
            recentExportPathsSet.insertObject_atIndex_(path, 0)
            Glyphs.defaults[ExportRecentExportPathsKey] = recentExportPathsSet.array()
            self.setupRecentExportPathsButton()

    @objc.python_method
    def __file__(self):
        """Please leave this method unchanged"""
        return __file__
