import os
import re
import csv
import vtk, qt, ctk, slicer
import numpy as np
import locale
from slicer.ScriptedLoadableModule import *

class HUExportModule(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self,parent)
        parent.title = "ROI Statistics Export"
        parent.categories = ["ROIs"]
        parent.dependencies = []
        parent.contributors = ["Stefan Kaim, Thomas Hofmann"]
        parent.helpText = "Exports HU-Values for each Segments as CSV grouped in z-direciton."
        parent.acknowledgementText = "-"

class HUExportModuleWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(8)

        # Volume Selector
        self.volumeSelector = slicer.qMRMLNodeComboBox()
        self.volumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.volumeSelector.selectNodeUponCreation = True
        self.volumeSelector.setMRMLScene(slicer.mrmlScene)

        # Segment Lists
        self.availableSegmentsList = qt.QListWidget()
        self.selectedSegmentsList = qt.QListWidget()
        self.addSegmentButton = qt.QPushButton("→")
        self.removeSegmentButton = qt.QPushButton("←")
        self.addSegmentButton.clicked.connect(self.addSelectedSegments)
        self.removeSegmentButton.clicked.connect(self.removeSelectedSegments)

        # Lists Button Layout
        buttonLayout = qt.QVBoxLayout()
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.addSegmentButton)
        buttonLayout.addWidget(self.removeSegmentButton)
        buttonLayout.addStretch(1)

        segmentSelectionLayout = qt.QHBoxLayout()
        segmentSelectionLayout.addWidget(self.availableSegmentsList)
        segmentSelectionLayout.addLayout(buttonLayout)
        segmentSelectionLayout.addWidget(self.selectedSegmentsList)

        # Export Path
        self.outputPathButton = ctk.ctkDirectoryButton()
        self.outputPathButton.directory = qt.QDir.homePath()

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.clicked.connect(self.exportCSV)

        self.statusLabel = qt.QLabel("")
        
        # Form Layout
        formLayout = qt.QFormLayout()
        formLayout.addRow("CT Volume:", self.volumeSelector)
        formLayout.addRow("Segments:", segmentSelectionLayout)
        formLayout.addRow("Export Folder:", self.outputPathButton)
        formLayout.addRow(self.exportButton)
        formLayout.addRow(self.statusLabel)
        self.layout.addLayout(formLayout)
        
        self.layout.addStretch(1)

        self.updateAvailableSegments()

    def updateSegmentDropdown(self):
        self.segmentDropdown.clear()
        segmentationNode = self.segmentationSelector.currentNode()
        if segmentationNode:
            segmentation = segmentationNode.GetSegmentation()
            for i in range(segmentation.GetNumberOfSegments()):
                name = segmentation.GetNthSegment(i).GetName()
                self.segmentDropdown.addItem(name)
    
    @staticmethod
    def cleanName(name):
        return re.sub(r'[<>:"/\\|?*\']','', name)
    
    def updateAvailableSegments(self):
        self.availableSegmentsList.clear()
        self.selectedSegmentsList.clear()
        
        segmentationNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for segNode in segmentationNodes:
            segmentation = segNode.GetSegmentation()
            for i in range(segmentation.GetNumberOfSegments()):
                segName = segmentation.GetNthSegment(i).GetName()
                listEntry = f"{segNode.GetName()}::{segName}"
                self.availableSegmentsList.addItem(listEntry)
    
    def addSelectedSegments(self):
        for item in self.availableSegmentsList.selectedItems():
            self.selectedSegmentsList.addItem(item.text())
            self.availableSegmentsList.takeItem(self.availableSegmentsList.row(item))
    
    def removeSelectedSegments(self):
        for item in self.selectedSegmentsList.selectedItems():
            self.availableSegmentsList.addItem(item.text())
            self.selectedSegmentsList.takeItem(self.selectedSegmentsList.row(item))

    def exportCSV(self):
        volumeNode = self.volumeSelector.currentNode()
        selectedSegments = [self.selectedSegmentsList.item(i).text() for i in range(self.selectedSegmentsList.count)]
        outputFolder = self.outputPathButton.directory
        
        if not volumeNode:
            self.statusLabel.setText("A CT-Volume needs to be selected!")
            return
        
        if not selectedSegments:
            self.statusLabel.setText("A Segment needs to be selected!")
            return
        
        exportCount = 0

        for fullName in selectedSegments:
            if "::" not in fullName:
                continue

            segNodeName, segmentName = fullName.split("::", 1)

            try:
                segmentationNode = slicer.util.getNode(segNodeName)
            except slicer.util.MRMLNodeNotFoundException:
                self.statusLabel.setText(f"Segment {segNodeName} not found! Continue using next segment.")
                continue

            segmentID = None
            for segIndex in range(segmentationNode.GetSegmentation().GetNumberOfSegments()):
                currentID = segmentationNode.GetSegmentation().GetNthSegmentID(segIndex)
                currentSegment = segmentationNode.GetSegmentation().GetSegment(currentID)
                if currentSegment.GetName() == segmentName:
                    segmentID = currentID
                    break

            if not segmentID:
                self.statusLabel.setText(f"Segment '{segmentName}' not found.")
                continue

            labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "Temp_Labelmap")
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(segmentationNode, [segmentID], labelmapNode, volumeNode)

            ctArray = slicer.util.arrayFromVolume(volumeNode)
            labelArray = slicer.util.arrayFromVolume(labelmapNode)

            ijkToRAS = vtk.vtkMatrix4x4()
            volumeNode.GetIJKToRASMatrix(ijkToRAS)
            z_ras_coords = [ijkToRAS.MultiplyPoint([0, 0, z, 1.0])[2] for z in range(ctArray.shape[0])]
            
            safeVolumeName = self.cleanName(volumeNode.GetName())
            safeSegNodeName = self.cleanName(segNodeName)
            safeSegmentName = self.cleanName(segmentName)

            locale.setlocale(locale.LC_ALL, '')

            decimal_point = locale.localeconv()["decimal_point"]
            csv_delimiter = ';' if decimal_point == ',' else ','

            sliceResults = []
            for z in range(ctArray.shape[0]):
                sliceCT = ctArray[z]
                sliceMask = labelArray[z] > 0
                huValues = sliceCT[sliceMask]
                if huValues.size > 0:
                    def fmt(x): return locale.format_string("%.9f", x, grouping=True)
                    sliceResults.append({
                        "SliceIndex": str(z),
                        "Z_Slice_mm": fmt(z_ras_coords[z]),
                        "Mean": fmt(np.mean(huValues)),
                        "StdDev": fmt(np.std(huValues)),
                        "Min": fmt(np.min(huValues)),
                        "Max": fmt(np.max(huValues)),
                        "VoxelCount": str(huValues.size),
                        "StdErr": fmt(np.std(huValues) / np.sqrt(huValues.size))
                    })

            outputPath = os.path.join(outputFolder, f"{safeVolumeName}_{safeSegNodeName}_{safeSegmentName}_statistics.csv")
            with open(outputPath, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=["SliceIndex", "Z_Slice_mm", "Mean", "StdDev", "Min", "Max", "VoxelCount", "StdErr"], delimiter=csv_delimiter)
                writer.writeheader()
                for row in sliceResults:
                    writer.writerow(row)
            
            exportCount += 1

        self.statusLabel.setText(f"Exported {exportCount} segment(s) to :\n{outputFolder}")
