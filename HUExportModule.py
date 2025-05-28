import os
import re
import csv
import vtk, qt, ctk, slicer
import numpy as np
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

        # Segmentation Selector
        self.segmentationSelector = slicer.qMRMLNodeComboBox()
        self.segmentationSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
        self.segmentationSelector.selectNodeUponCreation = True
        self.segmentationSelector.setMRMLScene(slicer.mrmlScene)
        self.segmentationSelector.currentNodeChanged.connect(self.updateSegmentDropdown)

        # Segment DropDown
        self.segmentDropdown = qt.QComboBox()

        # Export Path
        self.outputPathButton = ctk.ctkDirectoryButton()
        self.outputPathButton.directory = qt.QDir.homePath()

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.clicked.connect(self.exportCSV)

        self.statusLabel = qt.QLabel("")
        
        # Form Layout
        formLayout = qt.QFormLayout()
        formLayout.addRow("CT Volume:", self.volumeSelector)
        formLayout.addRow("Segmentation:", self.segmentationSelector)
        formLayout.addRow("Choose Segment:", self.segmentDropdown)
        formLayout.addRow("Export Folder:", self.outputPathButton)
        formLayout.addRow(self.exportButton)
        formLayout.addRow(self.statusLabel)
        self.layout.addLayout(formLayout)
        
        self.layout.addStretch(1)

    def updateSegmentDropdown(self):
        self.segmentDropdown.clear()
        segmentationNode = self.segmentationSelector.currentNode()
        if segmentationNode:
            segmentation = segmentationNode.GetSegmentation()
            for i in range(segmentation.GetNumberOfSegments()):
                name = segmentation.GetNthSegment(i).GetName()
                self.segmentDropdown.addItem(name)
    
    def cleanName(name):
        return re.sub(r'[<>:"/\\|?*\']','', name)

    def exportCSV(self):
        volumeNode = self.volumeSelector.currentNode()
        segmentationNode = self.segmentationSelector.currentNode()
        segmentName = self.segmentDropdown.currentText.strip()
        outputFolder = self.outputPathButton.directory
        
        if not volumeNode:
            self.statusLabel.setText("A CT-Volume needs to be selected!")
            return
        
        if not segmentationNode:
            self.statusLabel.setText("A Segmentation needs to be selected!")
            return
        
        if not segmentName:
            self.statusLabel.setText("A Segment needs to be selected!")
            return

        segmentID = None
        for segIndex in range(segmentationNode.GetSegmentation().GetNumberOfSegments()):
            currentID = segmentationNode.GetSegmentation().GetNthSegmentID(segIndex)
            currentSegment = segmentationNode.GetSegmentation().GetSegment(currentID)
            if currentSegment.GetName() == segmentName:
                segmentID = currentID
                break

        if not segmentID:
            self.statusLabel.setText(f"Segment '{segmentName}' not found.")
            return

        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "Temp_Labelmap")
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(segmentationNode, [segmentID], labelmapNode, volumeNode)

        ctArray = slicer.util.arrayFromVolume(volumeNode)
        labelArray = slicer.util.arrayFromVolume(labelmapNode)

        ijkToRAS = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASMatrix(ijkToRAS)
        z_ras_coords = [ijkToRAS.MultiplyPoint([0, 0, z, 1.0])[2] for z in range(ctArray.shape[0])]
        
        volumeName = cleanName(volumeNode.GetName())

        sliceResults = []
        for z in range(ctArray.shape[0]):
            sliceCT = ctArray[z]
            sliceMask = labelArray[z] > 0
            huValues = sliceCT[sliceMask]
            if huValues.size > 0:
                def fmt(x): return str(x).replace('.', ',')
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

        outputPath = os.path.join(outputFolder, f"{volumeName}_{segmentName}_statistics.csv")
        with open(outputPath, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=["SliceIndex", "Z_Slice_mm", "Mean", "StdDev", "Min", "Max", "VoxelCount", "StdErr"], delimiter=';')
            writer.writeheader()
            for row in sliceResults:
                writer.writerow(row)

        self.statusLabel.setText(f"Exported to :\n{outputPath}")
