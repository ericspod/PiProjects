#! /usr/bin/env python

'''
Copyright (C) 2016-8 Eric Kerfoot, all rights reserved, see LICENSE file

Simple thermal camera based on the AMG8833 (https://www.adafruit.com/product/3538) and PiTFT Plus 320x240 2.8"
TFT + Resistive Touchscreen (https://www.adafruit.com/product/2298).
'''

from __future__ import print_function
import os, time, datetime
import pygame
from PIL import Image
import numpy as np
import matplotlib.pyplot as plt
from Adafruit_AMG88xx import Adafruit_AMG88xx
from gpiozero import Button

MINTEMP=0
MAXTEMP=80
WIDTH=8
HEIGHT=8

# rescale mode for camera values
ranges=[(None,None),(MINTEMP,MAXTEMP-40),(MINTEMP,MAXTEMP),(MINTEMP+15,MAXTEMP-40),(MINTEMP+20,MAXTEMP)]

# color maps from matplotlib
cmaps=['inferno','gist_heat','hot','bwr','coolwarm','gist_rainbow','gray']

doRun=True # loop condition
saveShot=0 # set to 1 to take screenshot, 2 to display
rangeMode=0 # 0=(min,max), otherwise= ranges[rangeMode]
mapMode=0 # = cmaps[mapMode]


def quit():
    global doRun
    doRun=False


def toggleMode():
    global rangeMode
    rangeMode=(rangeMode+1)%len(ranges)


def toggleMaps():
    global mapMode
    mapMode=(mapMode+1)%len(cmaps)


def rescaleMode(im,mode):
    '''
    Rescale the input image `im' to unit values based on `mode': if 0 then rescale from minimum to maximum, otherwise
    rescale by indexed range in ranges.
    '''
    if mode==0:
        minv=im.min()
        maxv=im.max()
    else:
        minv,maxv=ranges[mode]
    
    # rescale image to unit values (pixels values between 0 and 1) based on the given minv and maxv thresholds
    if maxv>minv:
        im=(im-minv)/(maxv-minv)
        
    return np.clip(im,0,1),minv,maxv


def save():
    global saveShot
    saveShot=(saveShot+1)%3
    

stopbutton=Button(17)
stopbutton.when_pressed=quit
    
modebutton=Button(22)
modebutton.when_pressed=toggleMode
    
mapbutton=Button(23)
mapbutton.when_pressed=toggleMaps

savebutton=Button(27)
savebutton.when_pressed=save

sensor = Adafruit_AMG88xx()

os.putenv('SDL_FBDEV', '/dev/fb1')
pygame.init()

font = pygame.font.SysFont("monospace", 15)

surf=pygame.display.set_mode((0,0),pygame.FULLSCREEN|pygame.DOUBLEBUF)
pygame.mouse.set_visible(False)

basebuffer=np.ndarray((WIDTH*HEIGHT,),np.float64)
pixels=basebuffer.reshape((WIDTH,HEIGHT))
pixels=np.rot90(pixels,3)

mindim=min(*surf.get_size())

while(doRun):
    if saveShot==0: # display output from camera
        cm = plt.get_cmap(cmaps[mapMode])
        
        basebuffer[:]=sensor.readPixels()
        im,minp,maxp=rescaleMode(pixels,rangeMode)
        im=cm(im)
        
        im=Image.fromarray((im[...,:3]*255).astype(np.uint8))
        im = im.resize((mindim,mindim), Image.BICUBIC)
    
    elif saveShot==1: # capture output from camera to file
        saveShot=2 # change state to wait with current image
        filename=datetime.datetime.now().strftime('IR_%Y%m%d_%H%M%S.png')
        im.save(filename)
    else: # display captured file until button pressed again
        time.sleep(0.5)
    
    pim = pygame.image.fromstring(im.tobytes(),im.size,im.mode)
    label = font.render('Min: %.2i Max: %.2i'%(minp,maxp), 1, (255,255,255))
    
    surf.fill((0,0,0))
    surf.blit(pim,(0,0))    
    surf.blit(label, (mindim+15, 15))
    
    pygame.display.update()
    