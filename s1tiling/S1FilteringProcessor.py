#!/usr/bin/python
#-*- coding: utf-8 -*-
# =========================================================================
#   Program:   S1Processor
#
#   Copyright (c) CESBIO. All rights reserved.
#
#   See LICENSE for details.
#
#   This software is distributed WITHOUT ANY WARRANTY; without even
#   the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
#   PURPOSE.  See the above copyright notices for more information.
#
# =========================================================================
#
# Authors: Thierry KOLECK (CNES)
#
# =========================================================================

""" This module contains the multitemporal speckle filtering processor """

import glob, os, joblib, time
from subprocess import Popen
import pickle
from osgeo import gdal, gdalconst

class S1FilteringProcessor():
    def __init__(self,cfg):
        self.Cg_Cfg=cfg

    def process(self,tile):
        """Main function for speckle filtering script"""
        directory = os.path.join(self.Cg_Cfg.output_preprocess,tile.upper())
        print ("Start speckle filtering: "+tile.upper())
        filelist_s1ades = ""
        filelist_s1aasc = ""
        filelist_s1bdes = ""
        filelist_s1basc = ""
        for file_it in glob.glob(os.path.join(directory, "s1a*DES*.tif")):
            if "BorderMask" in file_it:
                continue
            filelist_s1ades = filelist_s1ades+" "+file_it
        for file_it in glob.glob(os.path.join(directory, "s1a*ASC*.tif")):
            if "BorderMask" in file_it:
                continue
            filelist_s1aasc = filelist_s1aasc+" "+file_it
        for file_it in glob.glob(os.path.join(directory, "s1b*DES*.tif")):
            if "BorderMask" in file_it:
                continue
            filelist_s1bdes = filelist_s1bdes+" "+file_it
        for file_it in glob.glob(os.path.join(directory, "s1b*ASC*.tif")):
            if "BorderMask" in file_it:
                continue
            filelist_s1basc = filelist_s1basc+" "+file_it
    
        if self.Cg_Cfg.Reset_outcore:
            processed_files = []
            try:
                os.remove(os.path.join(directory,"outcore.txt"))
            except:
                pass
        else:
            try:
                processed_files = joblib.load(os.path.join(directory, "outcore.txt"))
            except pickle.PickleError:
                processed_files = []

        filelist_s1ades_updateoutcore = filelist_s1ades
        filelist_s1aasc_updateoutcore = filelist_s1aasc
        filelist_s1bdes_updateoutcore = filelist_s1bdes
        filelist_s1basc_updateoutcore = filelist_s1basc
           
        for file_it in processed_files:
            filelist_s1ades_updateoutcore = filelist_s1ades_updateoutcore.replace(file_it, "")
            filelist_s1aasc_updateoutcore = filelist_s1aasc_updateoutcore.replace(file_it, "")
            filelist_s1bdes_updateoutcore = filelist_s1bdes_updateoutcore.replace(file_it, "")
            filelist_s1basc_updateoutcore = filelist_s1basc_updateoutcore.replace(file_it, "")

        pids = []
        if filelist_s1ades_updateoutcore.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                      +"otbcli_MultitempFilteringOutcore -progress false -inl"\
                      +filelist_s1ades_updateoutcore+" -oc "\
                      +os.path.join(directory, "outcore_S1aDES.tif")\
                      +" -wr {}".format(self.Cg_Cfg.Window_radius)
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile, stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        if filelist_s1aasc_updateoutcore.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                      +"otbcli_MultitempFilteringOutcore -progress false -inl"\
                      +filelist_s1aasc_updateoutcore+" -oc "\
                      +os.path.join(directory, "outcore_S1aASC.tif")\
                      +" -wr "+str(self.Cg_Cfg.Window_radius)
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile, stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        if filelist_s1bdes_updateoutcore.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                      +"otbcli_MultitempFilteringOutcore -progress false -inl"\
                      +filelist_s1bdes_updateoutcore+" -oc "\
                      +os.path.join(directory, "outcore_S1bDES.tif")\
                      +" -wr "+str(self.Cg_Cfg.Window_radius)
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile, stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        if filelist_s1basc_updateoutcore.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                      +"otbcli_MultitempFilteringOutcore -progress false -inl"\
                      +filelist_s1basc_updateoutcore+" -oc "\
                      +os.path.join(directory, "outcore_S1bASC.tif")\
                      +" -wr "+str(self.Cg_Cfg.Window_radius)
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile, stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        try:
            os.makedirs(os.path.join(directory, "filtered"))
        except os.error:
            pass

        title="Compute outcore"
        nb_cmd=len(pids)
        print (title+"... 0%")
        while len(pids) > 0:

            for i, pid in enumerate(pids):
                status = pid[0].poll()
                if status is not None and status != 0:
                   print ("Error in pid #"+str(i)+" id="+str(pid[0]))
                   print (pid[1])
                   del pids[i]
                   break

                if status == 0:
                   del pids[i]
                   print (title+"... "+str(int((nb_cmd-len(pids))*100./nb_cmd))+"%")
                   time.sleep(0.2)
                   break

        processed_files = processed_files+filelist_s1ades_updateoutcore.split()\
                     +filelist_s1aasc_updateoutcore.split()\
                     +filelist_s1bdes_updateoutcore.split()\
                     +filelist_s1basc_updateoutcore.split()

        joblib.dump(processed_files, os.path.join(directory, "outcore.txt"))
        # pickle.dump(processed_files, open(os.path.join(directory,"outcore.txt"), 'w'))
        pids = []
        if filelist_s1ades.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                      +"otbcli_MultitempFilteringFilter -progress false -inl"\
                      +filelist_s1ades+" -oc "\
                      +os.path.join(directory,"outcore_S1aDES.tif")\
                      +" -wr "+str(self.Cg_Cfg.Window_radius)+" -enl "\
                      +os.path.join(directory,"filtered","enl_S1aDES.tif")
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile, stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        if filelist_s1aasc.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                  +"otbcli_MultitempFilteringFilter -progress false -inl"\
                  +filelist_s1aasc+" -oc "\
                  +os.path.join(directory,"outcore_S1aASC.tif")\
                  +" -wr "+str(self.Cg_Cfg.Window_radius)+" -enl "\
                  +os.path.join(directory,"filtered","enl_S1aASC.tif")
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile,\
                          stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        if filelist_s1bdes.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                  +"otbcli_MultitempFilteringFilter -progress false -inl"\
                  +filelist_s1bdes+" -oc "\
                  +os.path.join(directory,"outcore_S1bDES.tif")\
                  +" -wr "+str(self.Cg_Cfg.Window_radius)+" -enl "\
                  +os.path.join(directory,"filtered","enl_S1bDES.tif")
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile,\
                          stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        if filelist_s1basc.strip() is not "":
            command = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.Cg_Cfg.OTBThreads)\
                  +"otbcli_MultitempFilteringFilter -progress false -inl"\
                  +filelist_s1basc+" -oc "\
                  +os.path.join(directory,"outcore_S1bASC.tif")\
                  +" -wr "+str(self.Cg_Cfg.Window_radius)+" -enl "\
                  +os.path.join(directory,"filtered","enl_S1bASC.tif")
            pids.append([Popen(command, stdout=self.Cg_Cfg.stdoutfile,\
                          stderr=self.Cg_Cfg.stderrfile, shell=True),command])

        title="Compute filtered images"
        nb_cmd=len(pids)
        print (title+"... 0%")
        while len(pids) > 0:

            for i, pid in enumerate(pids):
                status = pid[0].poll()
                if status is not None and status != 0:
                    print ("Error in pid #"+str(i)+" id="+str(pid[0]))
                    print (pid[1])
                    del pids[i]
                    break

                if status == 0:
                    del pids[i]
                    print (title+"... "+str(int((nb_cmd-len(pids))*100./nb_cmd))+"%")
                    time.sleep(0.2)
                    break

        filtering_directory = os.path.join(directory,'filtered/')
        for f in os.listdir(filtering_directory):
            fullpath = os.path.join(filtering_directory, f)
            if os.path.isfile(fullpath) and f.startswith('s1') and f.endswith('filtered.tif'):
                dst = gdal.Open(fullpath, gdal.GA_Update)
                dst.SetMetadataItem('FILTERED', 'true')
                dst.SetMetadataItem('FILTERING_WINDOW_RADIUS', str(self.Cg_Cfg.Window_radius))
