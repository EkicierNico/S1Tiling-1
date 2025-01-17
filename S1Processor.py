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
"""
This module contains a script to build temporal series of S1 images by tiles
It performs the following steps:
  1- Download S1 images from PEPS server
  2- Calibrate the S1 images to gamma0
  3- Orthorectify S1 images and cut their on geometric tiles
  4- Concatenante images from the same orbit on the same tile
  5- Build mask files
  6- Filter images by using a multiimage filter

 Parameters have to be set by the user in the S1Processor.cfg file
"""

import os, sys, glob, shutil, subprocess, datetime, argparse, configparser
import numpy as np
from PIL import Image
from subprocess import Popen
from s1tiling import S1FileManager, S1FilteringProcessor, Utils
from osgeo import gdal
from zipfile import ZipFile

def execute(cmd):
    try:
        print (cmd)
        subprocess.check_call(cmd, shell = True)
    except subprocess.CalledProcessError as e:
        print ('WARNING : Erreur dans la commande : ')
        print (e.returncode)
        print (e.cmd)
        print (e.output)

class Configuration():
    """This class handles the parameters from the cfg file"""
    def __init__(self,configFile):
        config = configparser.ConfigParser(os.environ)
        config.read(configFile)
        self.region=config.get('DEFAULT','region')
        self.output_preprocess=config.get('Paths','Output')
        self.raw_directory=config.get('Paths','S1Images')
        self.srtm=config.get('Paths','SRTM')
        self.tmpdir = config.get('Paths', 'tmp')
        if os.path.exists(self.tmpdir) == False:
            print ("ERROR: "+self.tmpdir+" is a wrong path")
            exit(1)
        self.GeoidFile=config.get('Paths','GeoidFile')
        self.pepsdownload=config.getboolean('PEPS','Download')
        self.ROI_by_tiles=config.get('PEPS','ROI_by_tiles')
        self.first_date=config.get('PEPS','first_date')
        self.last_date=config.get('PEPS','last_date')
        self.polarisation=config.get('PEPS','Polarisation')
        self.type_image="GRD"
        self.mask_cond=config.getboolean('Mask','Generate_border_mask')
        self.calibration_type=config.get('Processing','Calibration')
        self.removethermalnoise=config.getboolean('Processing','Remove_thermal_noise')
       
        self.out_spatial_res=config.getfloat('Processing','OutputSpatialResolution')
        
        self.output_grid=config.get('Processing','TilesShapefile')
        if os.path.exists(self.output_grid) == False:
            print ("ERROR: "+self.output_grid+" is a wrong path")
            exit(1)        

        self.SRTMShapefile=config.get('Processing','SRTMShapefile')
        if os.path.exists(self.SRTMShapefile) == False:
            print ("ERROR: "+self.srtm_shapefile+" is a wrong path")
            exit(1)
        self.grid_spacing=config.getfloat('Processing','Orthorectification_gridspacing')
        self.border_threshold=config.getfloat('Processing','BorderThreshold')
        try:
           tiles_file=config.get('Processing','TilesListInFile')
           self.tiles_list=open(tiles_file,'r').readlines()
           self.tiles_list = [s.rstrip() for s in self.tiles_list] 
           print (self.tiles_list)
        except:
           tiles=config.get('Processing','Tiles')
           self.tiles_list = [s.strip() for s in tiles.split(", ")]
        
        self.TileToProductOverlapRatio=config.getfloat('Processing','TileToProductOverlapRatio')
        self.Mode=config.get('Processing','Mode')
        self.nb_procs=config.getint('Processing','NbParallelProcesses')
        self.ram_per_process=config.getint('Processing','RAMPerProcess')
        self.OTBThreads=config.getint('Processing','OTBNbThreads')
        self.filtering_activated=config.getboolean('Filtering','Filtering_activated')
        self.Reset_outcore=config.getboolean('Filtering','Reset_outcore')
        self.Window_radius=config.getint('Filtering','Window_radius')

        self.stdoutfile = open("/dev/null", 'w')
        self.stderrfile = open("S1ProcessorErr.log", 'a')
        if "logging" in self.Mode:
            self.stdoutfile = open("S1ProcessorOut.log", 'a')
            self.stderrfile = open("S1ProcessorErr.log", 'a')
        if "debug" in self.Mode:
            self.stdoutfile = None
            self.stderrfile = None  
        
        self.cluster=config.getboolean('HPC-Cluster','Parallelize_tiles')

        def check_date (self):
            import datetime
            import sys
    
            fd=self.first_date
            ld=self.last_date

            try:
                F_Date = datetime.date(int(fd[0:4]),int(fd[5:7]),int(fd[8:10]))
                L_Date = datetime.date(int(ld[0:4]),int(ld[5:7]),int(ld[8:10]))
        
            except:
                print("Error : Unvalid date")
                sys.exit()
                
class Sentinel1PreProcess():
    """ This class handles the processing for Sentinel1 ortho-rectification """
    def __init__(self,cfg):
        try:
            os.remove("S1ProcessorErr.log.log")
            os.remove("S1ProcessorOut.log")
        except os.error:
            pass
        self.cfg=cfg      
        
    def generate_border_mask(self, all_ortho):
                """
                This method generate the border mask files from the
                orthorectified images.

                Args:
                  all_ortho: A list of ortho-rectified S1 images
                  """
                cmd_bandmath = []
                cmd_morpho = []
                files_to_remove = []
                print ("Generate Mask ...")
                for current_ortho in all_ortho:
                    if "vv" not in current_ortho:
                        continue
                    working_directory = os.path.split(current_ortho)[0]
                    name_border_mask = os.path.split(current_ortho)[1]\
                                              .replace(".tif", "_BorderMask.tif")
                    name_border_mask_tmp = os.path.split(current_ortho)[1]\
                                                .replace(".tif", "_BorderMask_TMP.tif")
                    files_to_remove.append(os.path.join(working_directory,\
                                                        name_border_mask_tmp))
                    cmd_bandmath.append('export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.cfg.OTBThreads)+'otbcli_BandMath -ram '\
                                        +str(self.cfg.ram_per_process)\
                                        +' -il '+current_ortho\
                                        +' -out '+os.path.join(working_directory,\
                                                               name_border_mask_tmp)\
                                        +' uint8 -exp "im1b1==0?0:1"')

                    #due to threshold approximation

                    cmd_morpho.append('export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.cfg.OTBThreads)+"otbcli_BinaryMorphologicalOperation -ram "\
                                      +str(self.cfg.ram_per_process)+" -progress false -in "\
                                      +os.path.join(working_directory,\
                                                    name_border_mask_tmp)\
                                      +" -out "\
                                      +os.path.join(working_directory,\
                                                    name_border_mask)\
                                      +" uint8 -structype ball"\
                                      +" -structype.ball.xradius 5"\
                                      +" -structype.ball.yradius 5 -filter opening")

                self.run_processing(cmd_bandmath, title="   Mask building")
                self.run_processing(cmd_morpho, title="   Mask smoothing")
                for file_it in files_to_remove:
                    if os.path.exists(file_it) == True:
                        os.remove(file_it)
                print ("Generate Mask done")

    def cut_image_cmd(self, raw_raster):
        """
        This method remove pixels on the image borders.
        Args:
          raw_raster: list of raw S1 raster file to calibrate
        """
        def needToBeCrop(image_name, thr):
            imgpil = Image.open(image_name)
            ima = np.asarray(imgpil)
            nbNan = len(np.argwhere(ima==0))
            return nbNan>thr

        print ("Cutting ",len(raw_raster))
        for i in range(len(raw_raster)):
            for image in raw_raster[i][0].get_images_list():

                image = image.replace(".tiff","_calOk.tiff")
                image_ok = image.replace("_calOk.tiff", "_OrthoReady.tiff")
                image_mask=image.replace("_calOk.tiff","_mask.tiff")
                im1_name = image.replace(".tiff","test_nord.tiff")
                im2_name = image.replace(".tiff","test_sud.tiff")

                raster = gdal.Open(image)
                xsize = raster.RasterXSize
                ysize = raster.RasterYSize
                npmask= np.ones((ysize,xsize), dtype=bool)

                cut_overlap_range = 1000 # Nombre de pixel a couper sur les cotes. ici 500 = 5km
                cut_overlap_azimuth = 1600 # Nombre de pixels a couper sur le haut ou le bas
                thr_nan_for_cropping = cut_overlap_range*2 #Quand on fait les tests, on a pas encore couper les nan sur le cote, d'ou l'utilisatoin de ce thr

                execute('gdal_translate -srcwin 0 100 '+str(xsize)+' 1 '+image+' '+im1_name)
                execute('gdal_translate -srcwin 0 '+str(ysize-100)+' '+str(xsize)+' 1 '+image+' '+im2_name)

                crop1 = needToBeCrop(im1_name, thr_nan_for_cropping)
                crop2 = needToBeCrop(im2_name, thr_nan_for_cropping)

                npmask[:,0:cut_overlap_range]=0 # Coupe W
                npmask[:,(xsize-cut_overlap_range):]=0 # Coupe E
                if crop1 : npmask[0:cut_overlap_azimuth,:]=0 # Coupe N
                if crop2 : npmask[ysize-cut_overlap_azimuth:,:]=0 # Coupe S

                driver = gdal.GetDriverByName("GTiff")
                outdata = driver.Create(image_mask, xsize, ysize, 1, gdal.GDT_Byte)
                outdata.SetGeoTransform(raster.GetGeoTransform())##sets same geotransform as input
                outdata.SetProjection(raster.GetProjection())##sets same projection as input
                outdata.GetRasterBand(1).WriteArray(npmask)
                outdata.SetGCPs(raster.GetGCPs(),raster.GetGCPProjection())
                outdata.FlushCache() ##saves to disk!!
                outdata = None

                execute('export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.cfg.OTBThreads)+'otbcli_BandMath ' \
                               +"-ram "+str(self.cfg.ram_per_process)\
                               +" -progress false " \
                               +'-il {} {} -out {} -exp "im1b1*im2b1"'.format(image,image_mask,image_ok))

                if os.path.exists(image_mask) == True: os.remove(image_mask)
                if os.path.exists(image) == True: os.remove(image)
                if os.path.exists(im1_name) == True: os.remove(im1_name)
                if os.path.exists(im2_name) == True: os.remove(im2_name)
        print ("Cutting done ")

    def do_calibration_cmd(self, raw_raster):
        """
        This method performs radiometric calibration of raw S1 images.

        Args:
          raw_raster: list of raw S1 raster file to calibrate
        """
        all_cmd = []
        print ("Calibration ",len(raw_raster))
        
        for i in range(len(raw_raster)):

            for image in raw_raster[i][0].get_images_list():
                image_ok = image.replace(".tiff", "_calOk.tiff")
                if os.path.exists(image_ok) == True:
                    continue

                all_cmd.append('export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.cfg.OTBThreads)+"otbcli_SARCalibration"\
                               +" -ram "+str(self.cfg.ram_per_process)\
                               +" -progress false -in "+image\
                               +" -out "+image_ok+' -lut '+self.cfg.calibration_type \
                               +" -noise "+str(self.cfg.removethermalnoise).lower())

        self.run_processing(all_cmd, title="   Calibration "+self.cfg.calibration_type)

        for i in range(len(raw_raster)):
            for image in raw_raster[i][0].get_images_list():
                if os.path.exists(image.replace(".tiff", "_calOk.tiff")) == True:
                   #if os.path.exists(image_ok.replace(".tiff", ".geom")) == True:
                       #os.remove(image_ok.replace(".tiff", ".geom"))

                   #UNCOMMENT TO DELETE RAW DATA
                   if os.path.exists(image) == True:
                       #os.remove(image)
                       pass

        print ("Calibration done")

        
    def do_ortho_by_tile(self, raster_list, tile_name, tmp_srtm_dir):
        """
        This method performs ortho-rectification of a list of
        s1 images on given tile.

        Args:
          raster_list: list of raw S1 raster file to orthorectify
          tile_name: Name of the MGRS tile to generate
        """
        all_cmd = []
        output_files_list = []
        print ("Start orthorectification :",tile_name)
        for i in range(len(raster_list)):
            raster, tile_origin = raster_list[i]
            manifest = raster.get_manifest()

            for image in raster.get_images_list():
                image_ok = image.replace(".tiff", "_OrthoReady.tiff")
                current_date = Utils.get_date_from_s1_raster(image)
                current_polar = Utils.get_polar_from_s1_raster(image)
                current_platform = Utils.get_platform_from_s1_raster(image)
                current_orbit_direction = Utils.get_orbit_direction(manifest)
                current_relative_orbit = Utils.get_relative_orbit(manifest)
                out_utm_zone = tile_name[0:2]
                out_utm_northern = (tile_name[2] >= 'N')
                working_directory = os.path.join(self.cfg.output_preprocess,\
                                                 tile_name)
                if os.path.exists(working_directory) == False:
                    os.makedirs(working_directory)

                in_epsg = 4326
                out_epsg = 32600+int(out_utm_zone)
                if not out_utm_northern:
                    out_epsg = out_epsg+100

                conv_result = Utils.convert_coord([tile_origin[0]], in_epsg, out_epsg)
                (x_coord, y_coord,dummy) = conv_result[0]
                conv_result = Utils.convert_coord([tile_origin[2]], in_epsg, out_epsg)
                (lrx, lry,dummy) = conv_result[0]
 
                if not out_utm_northern and y_coord < 0:
                    y_coord = y_coord+10000000.
                    lry = lry+10000000.

                ortho_image_name = current_platform\
                                   +"_"+tile_name\
                                   +"_"+current_polar\
                                   +"_"+current_orbit_direction\
                                   +'_{:0>3d}'.format(current_relative_orbit)\
                                   +"_"+current_date\
                                   +".tif"

                if not os.path.exists(os.path.join(working_directory,ortho_image_name)) and not os.path.exists(os.path.join(working_directory,ortho_image_name[:-11]+"txxxxxx.tif")):                    
                    cmd = 'export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.cfg.OTBThreads)+"otbcli_OrthoRectification -opt.ram "\
                      +str(self.cfg.ram_per_process)\
                      +" -progress false -io.in "+image_ok\
                      +" -io.out \""+os.path.join(working_directory,\
                                                  ortho_image_name)\
                      +"?&writegeom=false\" -interpolator nn -outputs.spacingx "\
                      +str(self.cfg.out_spatial_res)\
                      +" -outputs.spacingy -"+str(self.cfg.out_spatial_res)\
                      +" -outputs.sizex "\
                      +str(int(round(abs(lrx-x_coord)/self.cfg.out_spatial_res)))\
                      +" -outputs.sizey "\
                      +str(int(round(abs(lry-y_coord)/self.cfg.out_spatial_res)))\
                      +" -opt.gridspacing "+str(self.cfg.grid_spacing)\
                      +" -map utm -map.utm.zone "+str(out_utm_zone)\
                      +" -map.utm.northhem "+str(out_utm_northern).lower()\
                      +" -outputs.ulx "+str(x_coord)\
                      +" -outputs.uly "+str(y_coord)\
                      +" -elev.dem "+tmp_srtm_dir+" -elev.geoid "+self.cfg.GeoidFile

                    all_cmd.append(cmd)
                    output_files_list.append(os.path.join(working_directory,\
                                                      ortho_image_name))

        self.run_processing(all_cmd, title="Orthorectification")

        # Writing the metadata
        for f in os.listdir(working_directory):
            fullpath = os.path.join(working_directory, f)
            if os.path.isfile(fullpath) and f.startswith('s1') and f.endswith('.tif'):
                dst = gdal.Open(fullpath, gdal.GA_Update)
                oin = f.split('_')

                dst.SetMetadataItem('S2_TILE_CORRESPONDING_CODE', tile_name)
                dst.SetMetadataItem('PROCESSED_DATETIME', str(datetime.datetime.now().strftime('%Y:%m:%d')))
                dst.SetMetadataItem('ORTHORECTIFIED', 'true')
                dst.SetMetadataItem('CALIBRATION', str(self.cfg.calibration_type))
                dst.SetMetadataItem('SPATIAL_RESOLUTION', str(self.cfg.out_spatial_res))
                dst.SetMetadataItem('IMAGE_TYPE', 'GRD')
                dst.SetMetadataItem('FLYING_UNIT_CODE', oin[0])
                dst.SetMetadataItem('POLARIZATION', oin[2])
                dst.SetMetadataItem('ORBIT', oin[4])
                dst.SetMetadataItem('ORBIT_DIRECTION', oin[3])
                if oin[5][9] == 'x':
                    date = oin[5][0:4]+':'+oin[5][4:6]+':'+oin[5][6:8]+' 00:00:00'
                else:
                    date = oin[5][0:4]+':'+oin[5][4:6]+':'+oin[5][6:8]+' '+oin[5][9:11]+':'+oin[5][11:13]+':'+oin[5][13:15]
                dst.SetMetadataItem('ACQUISITION_DATETIME', date)

        return output_files_list

    def concatenate_images(self,tile):
        """
        This method concatenates images sub-swath for all generated tiles.
        """
        print ("Start concatenation :",tile)
        cmd_list = []
        files_to_remove = []

        image_list = [i for i in os.walk(os.path.join(self.cfg.output_preprocess, tile)).__next__()[2] if (len(i) == 40 and "xxxxxx" not in i)]
        image_list.sort()
            
        while len(image_list) > 1:

            image_sublist=[i for i in image_list if (image_list[0][:29] in i)]

            if len(image_sublist) >1 :
                images_to_concatenate=[os.path.join(self.cfg.output_preprocess, tile,i) for i in image_sublist]
                files_to_remove=files_to_remove+images_to_concatenate
                output_image = images_to_concatenate[0][:-10]+"xxxxxx"+images_to_concatenate[0][-4:]

                # build the expression for BandMath for concanetation of many images
                # for each pixel, the concatenation consists in selecting the first non-zero value in the time serie
                expression="(im%sb1!=0 ? im%sb1 : 0)" % (str(len(images_to_concatenate)),str(len(images_to_concatenate)))
                for i in range(len(images_to_concatenate)-1,0,-1):
                    expression="(im%sb1!=0 ? im%sb1 : %s)" % (str(i),str(i),expression)
                cmd_list.append('export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.cfg.OTBThreads)+'otbcli_BandMath -progress false -ram '\
                                   +str(self.cfg.ram_per_process)\
                                    +' -il '+' '.join(images_to_concatenate)\
                                    +' -out '+output_image\
                                    + ' -exp "'+expression+'"')
                                    
                if self.cfg.mask_cond:
                    if "vv" in image_list[0]:
                        images_msk_to_concatenate = [i.replace(".tif", "_BorderMask.tif") for i in images_to_concatenate]
                        files_to_remove=files_to_remove+images_msk_to_concatenate
                        cmd_list.append('export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS={};'.format(self.cfg.OTBThreads)+'otbcli_BandMath -progress false -ram '\
                                    +str(self.cfg.ram_per_process)\
                                    +' -il '+' '.join(images_msk_to_concatenate)\
                                    +' -out '+output_image.replace(".tif",\
                                                                "_BorderMask.tif")\
                                    + ' -exp "'+expression+'"')
                
            for i in  image_sublist:
                image_list.remove(i)

                   
        self.run_processing(cmd_list, "Concatenation")

        for file_it in files_to_remove:
            if os.path.exists(file_it):
                os.remove(file_it)


    def run_processing(self, cmd_list, title=""):
        """
        This method executes a given command.
        Args:
          cmd_list: the command to run
          title: optional title
        """
        import time
        nb_cmd = len(cmd_list)
        pids = []

        while len(cmd_list) > 0 or len(pids) > 0:
            if (len(pids) < self.cfg.nb_procs) and (len(cmd_list) > 0):
                pids.append([Popen(cmd_list[0], stdout=self.cfg.stdoutfile,\
                                  stderr=self.cfg.stderrfile, shell=True),cmd_list[0]])
                cmd_list.remove(cmd_list[0])
            for i, pid in enumerate(pids):
                status = pid[0].poll()
                if status is not None and status != 0:
                    print ("Error in pid #"+str(i)+" id="+str(pid[0]))
                    print (pid[1])
                    del pids[i]
                    break
                    #sys.exit(status)
                if status == 0:
                    del pids[i]
                    print (title+"... "+str(int((nb_cmd-(len(cmd_list)\
                                                +len(pids)))*100./nb_cmd))+"%")
                    time.sleep(0.2)
                    break
        print (title+" done")


def mainproc(args):
    """ Main process """
    CFG = args.input

    Cg_Cfg=Configuration(CFG)
    S1_CHAIN = Sentinel1PreProcess(Cg_Cfg)
    S1_FILE_MANAGER = S1FileManager.S1FileManager(Cg_Cfg)

    # If inputs are zipped
    if args.zip:
        inp = glob.glob(os.path.join(Cg_Cfg.raw_directory, '*.zip'))
        for i in inp:
            with ZipFile(i, 'r') as zipObj:
                zipObj.extractall(Cg_Cfg.raw_directory)

    TILES_TO_PROCESS = []
    ALL_REQUESTED = False
    for tile_it in Cg_Cfg.tiles_list:
        print (tile_it)
        if tile_it == "ALL":
            ALL_REQUESTED = True
            break
        elif True:  #S1_FILE_MANAGER.tile_exists(tile_it):
            TILES_TO_PROCESS.append(tile_it)
        else:
            print("Tile "+str(tile_it)+" does not exist, skipping ...")

    # We can not require both to process all tiles covered by downloaded products
    # and and download all tiles

    if ALL_REQUESTED:
        if Cg_Cfg.pepsdownload and "ALL" in Cg_Cfg.roi_by_tiles:
            print ("Can not request to download ROI_by_tiles : ALL if Tiles : ALL."\
                +" Use ROI_by_coordinates or deactivate download instead")
            sys.exit(1)
        else:
            TILES_TO_PROCESS = S1_FILE_MANAGER.get_tiles_covered_by_products()
            print ("All tiles for which more than "\
                +str(100*Cg_Cfg.TileToProductOverlapRatio)\
                +"% of the surface is covered by products will be produced: "\
                +str(TILES_TO_PROCESS))

    if len(TILES_TO_PROCESS) == 0:
        print ("No existing tiles found, exiting ...")
        sys.exit(1)

    # Analyse SRTM coverage for MGRS tiles to be processed
    SRTM_TILES_CHECK = S1_FILE_MANAGER.check_srtm_coverage(TILES_TO_PROCESS)

    NEEDED_SRTM_TILES = []
    TILES_TO_PROCESS_CHECKED = []
    # For each MGRS tile to process
    for tile_it in TILES_TO_PROCESS:
        print ("Check SRTM coverage for ",tile_it)
        # Get SRTM tiles coverage statistics
        srtm_tiles = SRTM_TILES_CHECK[tile_it]
        current_coverage = 0
        current_NEEDED_SRTM_TILES = []
        # Compute global coverage
        for (srtm_tile, coverage) in srtm_tiles:
            current_NEEDED_SRTM_TILES.append(srtm_tile)
            current_coverage += coverage
        # If SRTM coverage of MGRS tile is enough, process it
        if current_coverage >= 1.:
            NEEDED_SRTM_TILES += current_NEEDED_SRTM_TILES
            TILES_TO_PROCESS_CHECKED.append(tile_it)
        else:
            # Skip it
            print ("WARNING: Tile "+str(tile_it)\
                +" has insuficient SRTM coverage ("+str(100*current_coverage)\
                +"%)")
            NEEDED_SRTM_TILES += current_NEEDED_SRTM_TILES
            TILES_TO_PROCESS_CHECKED.append(tile_it)


    # Remove duplicates
    NEEDED_SRTM_TILES = list(set(NEEDED_SRTM_TILES))

    print (str(S1_FILE_MANAGER.nb_images)+" images to process on "\
        +str(len(TILES_TO_PROCESS_CHECKED))+" tiles")

    if len(TILES_TO_PROCESS_CHECKED) == 0:
        print ("No tiles to process, exiting ...")
        sys.exit(1)

    print ("Required SRTM tiles: "+str(NEEDED_SRTM_TILES))

    SRTM_OK = True
    srtmpath = []
    for srtm_tile in NEEDED_SRTM_TILES:
        tile_path = os.path.join(Cg_Cfg.srtm, srtm_tile)
        if not os.path.exists(tile_path):
            SRTM_OK = False
            print (tile_path+" is missing")
        else:
            srtmpath.append(tile_path)

    if not SRTM_OK:
        print ("Some SRTM tiles are missing, exiting ...")
        sys.exit(1)
    else:
        # copy all needed SRTM file in a temp directory for orthorectification processing
        i = 0
        for srtm_p in srtmpath:
            srtm_tile = NEEDED_SRTM_TILES[i]
            os.system('cp {0:s} {1:s}'.format(srtm_p, os.path.join(S1_FILE_MANAGER.tmpsrtmdir, srtm_tile)))
            i = i + 1

    if not os.path.exists(Cg_Cfg.GeoidFile):
        print ("Geoid file does not exists ("+Cg_Cfg.GeoidFile+"), exiting ...")
        sys.exit(1)

    filteringProcessor=S1FilteringProcessor.S1FilteringProcessor(Cg_Cfg)

    for idx, tile_it in enumerate(TILES_TO_PROCESS_CHECKED):

        print ("Tile: "+tile_it+" ("+str(idx+1)+"/"+str(len(TILES_TO_PROCESS_CHECKED))+")")
        # keep only the 500's newer files
        safeFileList=sorted(glob.glob(os.path.join(Cg_Cfg.raw_directory,"*")),key=os.path.getctime)
        if len(safeFileList)> 500:
            for f in safeFileList[:len(safeFileList)-500]:
                print ("Remove : ",os.path.basename(f))
                shutil.rmtree(f)

        S1_FILE_MANAGER.download_images(tiles=tile_it)

        intersect_raster_list = S1_FILE_MANAGER.get_s1_intersect_by_tile(tile_it)

        if len(intersect_raster_list) == 0:
            print ("No intersections with tile "+str(tile_it))
            continue

        S1_CHAIN.do_calibration_cmd(intersect_raster_list)
        S1_CHAIN.cut_image_cmd(intersect_raster_list)

        raster_tiles_list = S1_CHAIN.do_ortho_by_tile(intersect_raster_list, tile_it, S1_FILE_MANAGER.tmpsrtmdir)
        if Cg_Cfg.mask_cond:
            S1_CHAIN.generate_border_mask(raster_tiles_list)

        S1_CHAIN.concatenate_images(tile_it)

        if Cg_Cfg.filtering_activated:
            filteringProcessor.process(tile_it)

        # Cleaning
        shutil.rmtree(S1_FILE_MANAGER.tmpsrtmdir)


## Main call
if __name__=="__main__":
    parser = argparse.ArgumentParser(description='Launch S1 Tiling')
    parser.add_argument('-i', '--input', help='Input config file (CFG)', type=str, required=True)
    parser.add_argument('-z', '--zip', help='If S1 are zipped', action="store_true")
    args = parser.parse_args()

    mainproc(args)

    # Exemple dl S1
    # python peps_download.py -a peps.txt -w /mnt/data_netapp/tmp/test_s1tiling/input -p GRD -m IW --lonmin 143 --lonmax 144 --latmin -36 --latmax -35 -c S1 -d 2019-01-01 -f 2019-03-01