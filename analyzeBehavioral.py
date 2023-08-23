#!/usr/bin/env python3
import os
import subprocess
import re
#import matplotlib.pyplot as plt
from enum import Enum, auto
from itertools import groupby
import math
from collections import OrderedDict
from scipy import stats
import numpy

loc = 'Data/results/'

class ImageTypes(Enum):
    Reward = "Reward"
    Control = "Control"

class DoorStates(Enum):
    High, Low = auto(), auto()

class PumpStates(Enum):
    On, Off = auto(), auto()

class Activity(Enum):
    Running, Poking = auto(), auto()

class Mouse:

    def __init__(self, cageNum, rotation_intervals, poke_events):
        self._cageNum = cageNum
        self._rotation_intervals = rotation_intervals
        self._poke_events = poke_events

    @property
    def rotation_intervals(self):
        return self._rotation_intervals
    
    @property
    def poke_events(self):
        return self._poke_events
    

class RotationInterval:
    #continguous series of wheel spins

    def __init__(self, halfTimes, image):
        self._halfTimes = []
        self._image = image
        self.viable = True
        self._rpms = [] #instantaneous speeds in rotations per minute
        raw_rpms = [] #prone to error, will be refined
        for i in range(1, len(halfTimes) -1):
            raw_rpms.append(60 /  (halfTimes[i+1] - halfTimes[i-1])) 
        #instantaneous speeds at beginning and end of rotation event
        raw_rpms.insert(0, 30 /  (halfTimes[1] - halfTimes[0]))
        raw_rpms.append(30 /  (halfTimes[-1] - halfTimes[-2])) #instantaneous speeds at beginning and end of rotation event 
        erratic = []
        for i in range(1, len(halfTimes) -1):
            if raw_rpms[i] > 200:
                erratic.append(i)
        for i in range(1, len(halfTimes) -1):
            if i not in erratic:
                self._rpms.append(raw_rpms[i])
                self._halfTimes.append(halfTimes[i])
        if len(self._halfTimes) < 2:
            self.viable = False


    def numRotations(self):
        return len(self._halfTimes) // 2

    def avgSpeed(self):
        #average speed in RPM
        return self.numRotations() * 60 / (self._halfTimes[-1] - self._halfTimes[0])

    @property
    def speeds(self):
        return self._rpms

    @property
    def startTime(self):
        return self._halfTimes[0]

    @property
    def midTime(self):
        return (self._halfTimes[-1] + self.halfTimes[0]) / 2

    @property
    def halfTimes(self):
        return self._halfTimes

    @property
    def image(self):
        return self._image

class PokeEvent:
    #series of repeated pokes

    def __init__(self, doorStates, doorTimes, pumpTimes, pumpStates, image):
        self._doorStates = doorStates
        self._doorTimes = doorTimes
        self._pumpTimes = pumpTimes
        self._pumpStates = pumpStates
        self._image = image
        self._imageAppearanceTime = image.latestAppearance()
        self._image.appearances.get(self._imageAppearanceTime).addPokeEvent(self) 
        #add this pokeEvent to the image appearance during which it occured
        s, t = self.successfulPokes()
        if s == 1:
            self.latency = t[0] -  self._imageAppearanceTime
            self.pokeTime = t[0]
        else:
            self.latency = None
            self.pokeTime = None


    def isSuccess(self):
        successful = False
        for p in self._pumpStates:
            if p is PumpStates.On:
                successful = True
        return successful

    def successfulPokes(self):
        num = 0
        times = []
        for p, t in zip(self._pumpStates, self._pumpTimes):
            if p is PumpStates.On:
                num += 1
                times.append(t - 0.003) #Pump is activated 3 ms after poke occurs
        return num, times

    def allPokes(self):
        num = 0
        times = []
        for p, t in zip(self._doorStates, self._doorTimes):
            if p is DoorStates.Low:
                num += 1
                times.append(t)
        return num, times

    def unsuccessfulPokes(self):
        successfulPokes = set(self.successfulPokes()[1])
        allPokes = set(self.allPokes()[1])
        unsuccessful = list(allPokes - successfulPokes)
        unsuccessful.sort()
        return len(unsuccessful), unsuccessful

    def totalPokesNoTimeout(self, grace=30):
        #returns total number of pokes EXCLUDING those that are failed due to image timeout
        ##i.e. after pump success
        critical_time = None
        for p, t in zip(self._pumpStates, self._pumpTimes):
            if p is PumpStates.On:
                critical_time = t 
        if critical_time is None or self.successfulPokes()[0] > 1:
            return self.allPokes()[0]
        else:
            beforeSuccessful = 0
            for dt in self._doorTimes:
                if dt <= critical_time or dt > critical_time + grace: #30 seconds grace period
                    beforeSuccessful += 1
            return int(math.ceil(beforeSuccessful / 2)) 
            #two door states constitute a full poke
            ##ceil necessary because only door opening documented before poke

    def drinkTimes(self):
        drinkStart = 0
        drinkTimes = []
        for p, t in zip(self._pumpStates, self._pumpTimes):
            if p is PumpStates.On:
                drinkStart = t
            else:
                drinkTimes.append(t - drinkStart)
        return drinkTimes

    @property
    def startTime(self):
        return self._doorTimes[0]

    @property
    def image(self):
        return self._image

    @property
    def doorTimes(self):
        return self._doorTimes

    @property
    def doorStates(self):
        return self._doorStates
    
    @property
    def pumpTimes(self):
        return self._pumpTimes

    @property
    def pumpStates(self):
        return self._pumpStates

    @property
    def imageAppearanceTime(self):
        return self._imageAppearanceTime
    
    @staticmethod
    def imagePerformance(poke_events, rewardImgs):
        outputCSV.write("Image Name, Appearances, Hits, Misses, Success Rate %, Latency Mean, Latency SEM\n")
        for ri in rewardImgs:
            hits = 0
            for pe in poke_events:
                if pe.image == ri and pe.isSuccess():
                    hits += 1 #poke events that occured in the presence of the reward image
            print('Reward image appearances for {0} >> {1}'.format(ri.name, ri.numAppearances))
            print('Hits/Successful Pokes >> ', hits)
            success_rate = hits * 100.0 / ri.numAppearances if ri.numAppearances else 'N/A'
            outputCSV.write('{0}, {1}, {2}, {3}, {4}, {5}, {6}\n'.format(ri.name, ri.numAppearances, hits, ri.numAppearances - hits, success_rate, ri.avg_latency, ri.SEM_latency))

class Appearance:

    def __init__(self, image, time):
        self._time = time
        self._image = image
        self._poke_events = []

    def addPokeEvent(self, poke_event):
        self._poke_events.append(poke_event)

    @property
    def poke_events(self):
        return self._poke_events

    @property
    def time(self):
        return self._time

    @property
    def image(self):
        return self._image
    
class Image:

    appearanceLog = OrderedDict()

    def __init__(self, name, imageType):
        self.name = name
        assert isinstance(imageType, ImageTypes), 'use ImageType enum to assign images'
        self.imageType = imageType
        self._appearanceTimes = []
        self._appearances = {}
        if imageType == ImageTypes.Reward:
            self.avg_latency = None
            self.SEM_latency = None

    def __eq__(self, other):
        return self.name == other.name and self.imageType == other.imageType

    def __hash__(self):
        return hash(self.name)

    def incrementAppearances(self, time):
        self._appearanceTimes.append(time)
        self._appearances[time] = Image.appearanceLog[time] = Appearance(self, time)

    @property
    def numAppearances(self):
        return len(self._appearanceTimes)

    @property
    def appearanceTimes(self):
        return self._appearanceTimes

    def latestAppearance(self):
        return self._appearanceTimes[-1]

    @property
    def appearances(self):
        return self._appearances
    

    @staticmethod
    def imageAtTime(time):
        appearances = list(Image.appearanceLog.keys())
        return Image.appearanceLog[max(filter(lambda k: k < time, appearances))].image
    

def cumulativeSuccess(poke_events):
    outcomes = [int(pe.isSuccess()) for pe in poke_events]
    print("Successful Poke Events: {0}".format(sum(outcomes)))
    #times = [pe.startTime for pe in poke_events]
    cumulative_success = 0
    total = 0
    cumulative_probabilities = []
    for outcome in outcomes:
        cumulative_success += outcome
        total += 1
        cumulative_probabilities.append(cumulative_success / total)
    plt.plot(cumulative_probabilities, marker='.')
    plt.ylabel('Cumulative Probability')
    plt.xlabel('Poke Events')
    plt.title('Poke Success Rate')
    plt.show()

def rpmTimeLapse(rotation_intervals, hour=None):
    if hour is not None:
        secondCutOffs = (hour-1) * 60**2, hour * 60**2
    else:
        secondCutOffs = 0, math.inf
    rot_intervals_subset = list(filter(lambda pe: pe.startTime >= secondCutOffs[0] and pe.startTime < secondCutOffs[1], rotation_intervals))
    #these are rotation intervals that occured within specified hour
    rot_ints_byImage = [list(g[1]) for g in groupby(sorted(rot_intervals_subset, key=lambda ri: ri.image.name), key=lambda ri: ri.image.name)]
    #groups rotation intervals by image
    data = []
    for rot_ints_eachImage in rot_ints_byImage:
        allSpeeds, allTimes = [], []
        for rot_int in rot_ints_eachImage:
            allSpeeds.append(rot_int.avgSpeed())
            allTimes.append(rot_int.midTime)
        img = rot_ints_eachImage[0].image
        datum, = plt.plot(allTimes, allSpeeds, marker='.', linestyle='None', label='{0} ({1})'.format(img.name, img.imageType.value))
        data.append(datum)
    plt.xlabel('Time')
    plt.ylabel('Speed in RPM')
    # plt.xlim(0, 500)
    plt.legend(handles=data)
    plt.show()

def setImageLatencies(poke_events, images):
    pe_by_imageAppTime = {} #poke events per image appearance times
    for pe in poke_events:
        if pe.latency is not None:
            pe_by_imageAppTime[pe.imageAppearanceTime] = pe
    rewardImgs = list(filter(lambda im: im.imageType is ImageTypes.Reward, images))
    rewardImgs.sort(key=lambda ri: ri.name)
    for ri in rewardImgs:
        img_latencies = []
        for img_app_time in ri.appearanceTimes:
            pe = pe_by_imageAppTime.get(img_app_time, None)
            if pe is not None:
                img_latencies.append(pe.latency)
        ri.avg_latency = numpy.mean(img_latencies)
        ri.SEM_latency = stats.sem(img_latencies)

def pokeLatencies(poke_events, images):
    print('\nTime of reward, Image, Poke Time, and Latencies (sec):')
    outputCSV.write('\nTime of reward, Image, Time of poke, Latencies (sec)\n')
    for ap in Image.appearanceLog.values():
        if ap.image.imageType != ImageTypes.Reward:
            continue
        if not ap.poke_events:
            outputCSV.write('{0}, {1}, TIMEOUT\n'.format(ap.time, ap.image.name))
        else:
            for pe in ap.poke_events:
                if pe.latency is not None:
                    outputCSV.write('{0}, {1}, {2}, {3}\n'.format(pe.imageAppearanceTime, pe.image.name, pe.pokeTime, pe.latency))
                else:
                    outputCSV.write('{0}, {1}, TIMEOUT\n'.format(pe.imageAppearanceTime, pe.image.name))


def pokesPerHour(poke_events):
    hourlyPokes = {} #dictionary stores pokes for each hour
    for pe in poke_events:
        for t, s in zip(pe.pumpTimes, pe.pumpStates): 
            if s is PumpStates.On:
                hr = int(t / 3600) + 1 #convert t to hours, round up for nth hour
                hourlyPokes[hr] = hourlyPokes.get(hr, 0) + 1 #increment pokes for each hour, default value of 0 supplied to initialize
    outputCSV.write('\nHour, # Successful Pokes\n')
    for k in range(1, 13):
        print("Successful pokes in hour #{0} >> {1}".format(k, hourlyPokes.get(k, 0)))
        outputCSV.write('{0}, {1}\n'.format(k, hourlyPokes.get(k, 0)))

def numPokes(poke_events):
    allPokes = [pe.allPokes()[0] for pe in poke_events]
    plt.hist(allPokes)
    plt.xlabel("Number of pokes per poke event")
    plt.ylabel("Frequency")
    plt.show()

def drinkLengths(poke_events):
    lengths = []
    for pe in poke_events:
        lengths.extend(pe.drinkTimes())
    plt.hist(lengths)
    plt.xlabel("Time (sec) drinking sugar water")
    plt.ylabel("Frequency")
    plt.show()

def endRun(wheelHalfTimes, image, rotation_intervals):
    if len(wheelHalfTimes) < 3:
        return
    rotation_intervals.append(RotationInterval(wheelHalfTimes, image)) #add this interval to list

def endPoke(doorStates, doorTimes, pumpTimes, pumpStates, image, poke_events):
    poke_events.append(PokeEvent(doorStates, doorTimes, pumpTimes, pumpStates, image))

def pruneRotationIntervals(rotation_intervals):
    erratic = []
    for ri in rotation_intervals:
        if not ri.viable:
            erratic.append(ri)
    for ri in erratic:
        rotation_intervals.remove(ri)

def pokeStatistics(poke_events, images, filename):
    successful = 0
    total = 0
    i=0
    for pe in poke_events:
        i += 1
        successful += pe.successfulPokes()[0]
        total += pe.totalPokesNoTimeout()
    rewardImgs = list(filter(lambda im: im.imageType is ImageTypes.Reward, images))
    try:
        rewardImgs.sort(key = lambda ri: float(re.findall(r"[-+]?[.]?[\d]+(?:,\d\d\d)*[\.]?\d*(?:[eE][-+]?\d+)?",ri.name)[0])) # sort images bycontrast level
    except IndexError:
        pass #image does not have contrast level specified
    PokeEvent.imagePerformance(poke_events, rewardImgs)
    if 'Night #1' in filename or 'Night 1' in filename:
        print('\n')
        return
    print('\n')
    
def getFileNames(location):
    prefixes = []
    fileNames = []
    def recursiveDirectories(loc):
        nonlocal fileNames
        try:
            for d in next(os.walk(loc))[1]:
                recursiveDirectories(loc + d + '/')
            for f in next(os.walk(loc))[2]:
                if 'Results' in f and '.txt' in f:
                    fileNames.append(loc + f)
        except StopIteration:
            pass
    recursiveDirectories(location)
    fileNames.sort()
    return fileNames

def initialize(allInput, filename, findFloat):
    images = []
    for line in allInput:
        if 'USB drive ID: ' in line:
            print("\n***********************************\n")
            print(filename)
            print(line)
            mouseNum = int(findFloat.search(line).group(0))
        elif 'Control image set:' in line:
            for img in line[line.find('[')+1:line.rfind(']')].split(','):
                images.append(Image(img.strip(), ImageTypes.Control))
        elif 'Reward image set:' in line:
            for img in line[line.find('[')+1:line.rfind(']')].split(','):
                images.append(Image(img.strip(), ImageTypes.Reward))
        elif "Start of experiment" in line:
            return images, "Mouse_{0}".format(mouseNum)

if not loc.endswith('/'):
    loc += '/'
for filename in getFileNames(loc):
    Image.appearanceLog = OrderedDict(); #reset appearances
    with open(filename, 'r') as resultFile:
        allInput = resultFile.readlines()
    findFloat = re.compile("[+-]?([0-9]*[.])?[0-9]+") #regex to search for a number (float)
    wheelHalfTimes, doorStates, doorTimes, pumpStates, pumpTimes, poke_events, rotation_intervals = [], [], [], [], [], [], []
    skipLine = False
    curImgName = None
    pokeInProgress = False
    images, identifier = initialize(allInput, filename, findFloat)
    images = set(images) #convert to set to avoid accidental duplication
    Image.images = images
    outputCSV = open(filename.replace(filename[filename.rfind('/')+1:], identifier + '.csv'), 'w')
    try:
        controlImgStart = [im for im in images if im.imageType == ImageTypes.Control][0]
    except IndexError:
        print("Warning: No control Images")
        outputCSV.write("WARNING: no control images defined")
        controlImgStart = [im for im in images][0]
    #ControlImgStart defined in case wheel or door activity is documented prior to first image appearance
    ##documentation. This occurs rarely and is a bug in the results file generation protocol.
    
    currentImg, pokeImg, runImg, currentState = controlImgStart, controlImgStart, controlImgStart, None

    for line in allInput:

        if 'starting' in line:
            continue

        elif 'Image' in line and 'Name:' in line:
            newImgName = line[line.find('Name:') + 5: line.find(',')].strip()
            if curImgName == newImgName: #this is a bug
                continue
            else:
                curImgName = newImgName
            currentImg = next((img for img in images if img.name == curImgName), None)
            assert currentImg is not None, 'Unrecognized image: {0}'.format(curImgName)
            currentImg.incrementAppearances(float(re.search("Time: (.*)", line).group(1)))

        elif 'Wheel' in line:
            if skipLine:
                skipLine = False
                continue
            if currentState is Activity.Poking:
                endPoke(doorStates, doorTimes, pumpTimes, pumpStates, pokeImg, poke_events)
                doorStates, doorTimes, pumpTimes, pumpStates = [], [], [], []
            currentState = Activity.Running
            if 'State:' in line:
                wheelHalfTimes.append(float(findFloat.search(line).group(0))) #appends times
            if 'revolution' in line:
                #need to skip next data point because wheel state does not actually change; it appears to be a bug
                skipLine = True
                continue #do NOT reset skipLine boolean

        elif 'Pump' in line:
            if re.search("State: (.*), Time", line).group(1) == 'On':
                pump_state = PumpStates.On 
                pokeImg = currentImg #the poke event's image should be the image when the pump is on (ie reward image)
                pokeInProgress = True #ensure parameters don't change within poke duration
            else:
                pump_state = PumpStates.Off
                pokeInProgress = False
            pumpStates.append(pump_state) 
            pumpTimes.append(float(findFloat.search(line).group(0)))

        elif 'Door' in line:
            if currentState is Activity.Running:
                endRun(wheelHalfTimes, currentImg, rotation_intervals)
                wheelHalfTimes = []
            if currentState is not Activity.Poking and not pokeInProgress:
                pokeImg = currentImg #record image when poke event starts
            currentState = Activity.Poking
            door_state = DoorStates.High if re.search("State: (.*), Time", line).group(1) == 'High' else DoorStates.Low
            doorStates.append(door_state)
            doorTimes.append(float(findFloat.search(line).group(0)))

        skipLine = False
    if currentState is Activity.Poking:
        endPoke(doorStates, doorTimes, pumpTimes, pumpStates, pokeImg, poke_events)
    else:
        endRun(wheelHalfTimes, currentImg, rotation_intervals)
    pruneRotationIntervals(rotation_intervals)

    ######### ANALYSIS FUNCTION CALLS BEGIN HERE; DO NOT EDIT ABOVE WHEN RUNNING ANALYSIS##############
    # cumulativeSuccess(poke_events)
    # rpmTimeLapse(rotation_intervals)
    # numPokes(poke_events)
    # drinkLengths(poke_events)
    setImageLatencies(poke_events, images)
    pokeStatistics(poke_events, images, filename)
    pokesPerHour(poke_events)
    pokeLatencies(poke_events, images)
    outputCSV.close() #DO NOT delete this line or data may be corrupted (not just results! DATA!!)




