# !/usr/bin/env/python3.6
#Install instructions for psutil - https://github.com/giampaolo/psutil/blob/master/INSTALL.rst
#Follow the same instructions for pygame

import os #Create directory
import sys #Allows program to exit on completion
import psutil #Gives access to USB drive mount events
import time #Gives access to delays and timing
from PIL import Image, ImageDraw #Draw images and save as PNG
from tkinter import font, Tk, Label, Entry, Frame, Checkbutton, Text, Scrollbar, Button, DoubleVar, IntVar, Radiobutton, Canvas, Widget #GUI library
from tkinter.ttk import Separator
from tkinter.constants import *
import re #REGEX library
import threading #Allow running the protocol generator as a separate thread to not lock the GUI
import queue #Allow kill flag to be sent to threads
from collections import OrderedDict #Create dictionaries where object order is preserved
if os.name != 'posix':
    import win32api #Get name of USB drive - windows only
import glob #Search for files in deirectory

nCages = 4 #Global variable declaring number of cages
imageWidth = 1366
imageHeight = 768

#From: https://gist.github.com/novel-yet-trivial/3eddfce704db3082e38c84664fc1fdf8
class VerticalScrolledFrame:
    """
    A vertically scrolled Frame that can be treated like any other Frame
    ie it needs a master and layout and it can be a master.
    :width:, :height:, :bg: are passed to the underlying Canvas
    :bg: and all other keyword arguments are passed to the inner Frame
    note that a widget layed out in this frame will have a self.master 3 layers deep,
    (outer Frame, Canvas, inner Frame) so
    if you subclass this there is no built in way for the children to access it.
    You need to provide the controller separately.
    """
    def __init__(self, master, **kwargs):
        width = kwargs.pop('width', None)
        height = kwargs.pop('height', None)
        bg = kwargs.pop('bg', kwargs.pop('background', None))
        self.outer = Frame(master, **kwargs)

        self.vsb = Scrollbar(self.outer, orient=VERTICAL)
        self.vsb.pack(fill=Y, side=RIGHT)
        self.canvas = Canvas(self.outer, highlightthickness=0, width=width, height=height, bg=bg)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.canvas['yscrollcommand'] = self.vsb.set
        # mouse scroll does not seem to work with just "bind"; You have
        # to use "bind_all". Therefore to use multiple windows you have
        # to bind_all in the current widget
        self.canvas.bind("<Enter>", self._bind_mouse)
        self.canvas.bind("<Leave>", self._unbind_mouse)
        self.vsb['command'] = self.canvas.yview

        self.inner = Frame(self.canvas, bg=bg)
        # pack the inner Frame into the Canvas with the topleft corner 4 pixels offset
        self.canvas.create_window(4, 4, window=self.inner, anchor='nw')
        self.inner.bind("<Configure>", self._on_frame_configure)

        self.outer_attr = set(dir(Widget))

    def __getattr__(self, item):
        if item in self.outer_attr:
            # geometry attributes etc (eg pack, destroy, tkraise) are passed on to self.outer
            return getattr(self.outer, item)
        else:
            # all other attributes (_w, children, etc) are passed to self.inner
            return getattr(self.inner, item)

    def _on_frame_configure(self, event=None):
        x1, y1, x2, y2 = self.canvas.bbox("all")
        height = self.canvas.winfo_height()
        self.canvas.config(scrollregion = (0,0, x2, max(y2, height)))

    def _bind_mouse(self, event=None):
        self.canvas.bind_all("<4>", self._on_mousewheel)
        self.canvas.bind_all("<5>", self._on_mousewheel)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mouse(self, event=None):
        self.canvas.unbind_all("<4>")
        self.canvas.unbind_all("<5>")
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        """Linux uses event.num; Windows / Mac uses event.delta"""
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units" )
        elif event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units" )

def buildGUI():
    ####See "def loadPreset()" to change default protocol settings###
    entryDict = {} #Values for the entry portion of the GUI - tuple - (label, var, entry)
    imageBarDict = {} #Outputs from image select check boxes
    prevImageBarVars = {} #Last recorded state of check boxes
    imageList = ['Solid', 'Checkerboard', 'Horizontal_Stripes', 'Vertical_Stripes'] #List of images available for a protocol
    presetList = [("Day #1", 1), ("Day #2", 2), ("Day #3", 3), ("Day #4", 4), ("Contrast", 5), ("Freq", 6)] #List of available presets
    radioList = [None]*len(presetList) #List of radiobutton objects
    presetVar = None #Preset protocol ID
    initialPreset = 1 #Starting preset value
    statusLabel = None #This label updates the user on the status of the program and the next required step
    metadataBox = None #Text box object that contains the metadata
    #entryList     #labelList
    entryDict = OrderedDict((("Minimum wheel revolutions for reward: ", None), #Label text for the entry frame
                             ("Maximum wheel revolutions for reward: ", None),
                             ("Maximum duration of reward state (seconds): ", None),
                             ("Duration of pump \"on\" state (seconds): ", None),
                             ("Maximum time between wheel events (seconds): ", None),
                             ("Total duration of the experiment (hours): ", None),
                             ("Pattern frequency for images: ", None),
                             ("Duration of each reward frame (seconds): ", None)))

    contrastDict = OrderedDict((("Number of contrast steps: ", None),
                                ("Minimum time between contrast increments: ", None),
                                ("Maximum time between contrast increments: ", None),
                                ("Minimum contrast ratio (0-100): ", None),
                                ("Maximum contrast ratio (0-100): ", None),
                                ("Calculated contrast step ratio: ", None)))

    frequencyDict = OrderedDict((("Number of frequency steps: ", None),
                                ("Minimum time between frequency increments: ", None),
                                ("Maximum time between frequency increments: ", None),
                                ("Minimum pattern frequency (2-" + str(round(imageWidth/2)) + "): ", None),
                                ("Maximum pattern frequency (2-" + str(round(imageWidth/2)) + "): ", None),
                                ("Calculated frequency step ratio: ", None)))

    protocolThread = None #Thread object for generating protocol file and exporting it to a USB drive
    killFlag = queue.Queue() #Queue object for passing kill flag to protocol thread from main thread

    def testbox(): #Make sure that there is at least one reward image selected
        nonlocal imageBarDict
        nonlocal prevImageBarVars
        nonlocal statusLabel
        nonlocal imageList
        nonlocal frameDict
        rSum = 0
        cSum = 0
        error = None

        if len(imageBarDict) == len(imageList): #Only check when GUI is fully populated
            for key, value in imageBarDict.items(): #Count number of active control and reward images
                cVar, rVar = value["var"]
                rSum += rVar.get()
                cSum += cVar.get()
            if rSum == 0: #If no reward image is selected, restore previous state
                error = 1
                statusLabel.config(text="ERROR: There must be at least one reward image in the protocol.")
            elif rSum > 1 and frameDict["contrast"].grid_info():
                error = 2
                statusLabel.config(text = "Set protocol parameters and press \"Upload\"...")
            else:
                statusLabel.config(text = "Set protocol parameters and press \"Upload\"...")
            for key, value in imageBarDict.items():
                cVar, rVar = value["var"]
                if len(prevImageBarVars) == len(imageBarDict): #If previous state is fully populated
                    prevC, prevR = prevImageBarVars[key]
                    if(error == 1): #If there is an error, set error back to original state
                        rVar.set(prevR)
                        cVar.set(prevC)
                    if(error == 2): #If contrast series, have check box act as a radio button
                        if(prevR):
                            rVar.set(0)
                prevImageBarVars[key] = (cVar.get(), rVar.get()) #Update previous state to current state

    #Verify that all entries in the GUI are valid
    def testEntry(proceed):
        nonlocal frameDict
        nonlocal entryDict
        nonlocal contrastDict
        nonlocal frequencyDict
        nonlocal statusLabel
        nonlocal imageBarDict
        nonlocal metadataBox
        nonlocal uploadButton
        nonlocal protocolThread
        nonlocal killFlag
        nonlocal uploadButton

        error = False
        if not None in entryDict.values(): #Only start proofreading if GUI is fully populated
            for key, value in entryDict.items(): #Check for any negative entries
                try:
                    if value["var"].get() < 0:
                        statusLabel.config(text="ERROR: " + key + " cannot be a negative value.")
                        error = True
                    if key in ["Minimum wheel revolutions for reward: ", "Maximum wheel revolutions for reward: "] and not value["var"].get().is_integer(): #These values can only be integers
                        statusLabel.config(text="ERROR: " + key + " must be an integer value.")
                        error = True
                except:
                    statusLabel.config(text="ERROR: " + key + " is not a valid number - check syntax.")
                    error = True

            if not error:
                if entryDict["Minimum wheel revolutions for reward: "]["var"].get() > entryDict["Maximum wheel revolutions for reward: "]["var"].get():
                    statusLabel.config(text="ERROR: minReward cannot be greater than maxReward.")
                    error = True

            if frameDict["contrast"].grid_info(): #If contrast options are active, verify text boxes
                for key, value in contrastDict.items(): #Check for any negative entries
                    try:
                        if value["var"].get() < 0:
                            statusLabel.config(text="ERROR: " + key + " cannot be a negative value.")
                            error = True
                        if key in "Number of contrast steps: " and not value["var"].get().is_integer(): #This values can only be integer
                            statusLabel.config(text="ERROR: " + key + " must be an integer value.")
                            error = True
                    except:
                        statusLabel.config(text="ERROR: " + key + " is not a valid number - check syntax.")
                        error = True

                if not error:
                    if contrastDict["Maximum time between contrast increments: "]["var"].get() < contrastDict["Minimum time between contrast increments: "]["var"].get():
                        statusLabel.config(text="ERROR: minTime cannot be greater than maxTime.")
                        error = True
                    if contrastDict["Maximum contrast ratio (0-100): "]["var"].get() < contrastDict["Minimum contrast ratio (0-100): "]["var"].get():
                        statusLabel.config(text="ERROR: minContrast cannot be greater than maxContrast.")
                        error = True
                    if contrastDict["Maximum contrast ratio (0-100): "]["var"].get() > 100:
                        statusLabel.config(text="ERROR: Contrast cannot be greater than 100%.")
                        error = True
                    if contrastDict["Number of contrast steps: "]["var"].get() < 2:
                        statusLabel.config(text="ERROR: There must be at least two contrast steps.")
                        error = True
                    contrastDict["Calculated contrast step ratio: "]["var"].set((contrastDict["Minimum contrast ratio (0-100): "]["var"].get()/contrastDict["Maximum contrast ratio (0-100): "]["var"].get())**(1/(contrastDict["Number of contrast steps: "]["var"].get()-1)))


            if not error and statusLabel is not None:
                statusLabel.config(text = "Set protocol parameters and press \"Upload\"...")

                if proceed:
                    if uploadButton['text'] == "Upload":
                        #Run the protocol generator as a separate thread from the GUI so that the GUI doesn't lock up
                        killFlag.put(1)
                        protocolThread = threading.Thread(target=uploadProtocol, args=(frameDict, entryDict, contrastDict, frequencyDict, imageBarDict, metadataBox, statusLabel, killFlag, uploadButton, presetVar, presetList))
                        toggleGUI('disabled')
                        protocolThread.start()
                        #protocolThread.join()
                    elif uploadButton['text'] == "Quit":
                        sys.exit()
                    else:
                        killFlag.put(0) #Kill protocol thread
                        while protocolThread.is_alive(): #Wait for thread to stop
                            time.sleep(0.1)
                        toggleGUI('normal') #restore GUI
            try: #Try needed as button may not exist yet while GUI is being assembled
                if(error):
                    uploadButton.config(state="disabled")
                else:
                    uploadButton.config(state="normal")
            except:
                pass
        return not error

    def loadPreset():
        nonlocal frameDict
        nonlocal entryDict
        nonlocal contrastDict
        nonlocal frequencyDict
        nonlocal imageBarDict
        nonlocal presetVar
        nonlocal presetList
        nonlocal statusLabel
        presetID = presetVar.get()
        statusLabel.config(text = "Set protocol parameters and press \"Upload\"...")
        maxFreqString = str()

        #Apply nonlocal defaults if preset option is selected
        if True:
            #Set default image check state to solid control and checkerboard reward
            for key, value in imageBarDict.items():
                cVar, rVar = value["var"]
                if(key == "Solid"):
                    rVar.set(0)
                    cVar.set(1)
                elif(key == "Vertical_Stripes"):
                    rVar.set(1)
                    cVar.set(0)
                else:
                    rVar.set(0)
                    cVar.set(0)

            #Inactivate entry boxes and check boxes
            for key, value in entryDict.items():
                value["entry"].config(state='disabled')
            for key, value in contrastDict.items():
                value["entry"].config(state='disabled')
            for key, value in frequencyDict.items():
                value["entry"].config(state='disabled')
            for key, value in contrastDict.items():
                value["entry"].config(state='disabled')
            for key, value in imageBarDict.items():
                cChk, rChk = value["chk"]
                cChk.config(state='disabled')
                rChk.config(state='disabled')

            #Hide contrast controls
            frameDict["contrast"].grid_remove()
            frameDict["frequency"].grid_remove()

 ############################DEFAULT PROTOCOLS##########################################################################################
            entryDict["Minimum wheel revolutions for reward: "]["var"].set(10)
            entryDict["Maximum wheel revolutions for reward: "]["var"].set(50)
            entryDict["Maximum duration of reward state (seconds): "]["var"].set(10)
            entryDict["Duration of pump \"on\" state (seconds): "]["var"].set(1)
            entryDict["Maximum time between wheel events (seconds): "]["var"].set(10)
            entryDict["Duration of each reward frame (seconds): "]["var"].set(entryDict["Maximum duration of reward state (seconds): "]["var"].get())
            entryDict["Pattern frequency for images: "]["var"].set(16)
            entryDict["Total duration of the experiment (hours): "]["var"].set(12)

            contrastDict["Number of contrast steps: "]["var"].set(8)
            contrastDict["Minimum time between contrast increments: "]["var"].set(5)
            contrastDict["Maximum time between contrast increments: "]["var"].set(contrastDict["Minimum time between contrast increments: "]["var"].get())
            contrastDict["Minimum contrast ratio (0-100): "]["var"].set(1)
            contrastDict["Maximum contrast ratio (0-100): "]["var"].set(100)
            contrastDict["Calculated contrast step ratio: "]["var"].set((contrastDict["Minimum contrast ratio (0-100): "]["var"].get()/contrastDict["Maximum contrast ratio (0-100): "]["var"].get())**(1/(contrastDict["Number of contrast steps: "]["var"].get()-1)))

            frequencyDict["Number of frequency steps: "]["var"].set(8)
            frequencyDict["Minimum time between frequency increments: "]["var"].set(5)
            frequencyDict["Maximum time between frequency increments: "]["var"].set(frequencyDict["Minimum time between frequency increments: "]["var"].get())
            frequencyDict["Minimum pattern frequency (2-" + str(round(imageWidth/2)) + "): "]["var"].set(2)
            frequencyDict["Maximum pattern frequency (2-" + str(round(imageWidth/2)) + "): "]["var"].set(100)
            frequencyDict["Calculated frequency step ratio: "]["var"].set((frequencyDict["Minimum pattern frequency (2-" + str(round(imageWidth/2)) + "): "]["var"].get()/frequencyDict["Maximum pattern frequency (2-" + str(round(imageWidth/2)) + "): "]["var"].get())**(1/(frequencyDict["Number of frequency steps: "]["var"].get()-1)))


            #On days 1 and 2, reward never times out
            if presetID <= 2:
                entryDict["Maximum duration of reward state (seconds): "]["var"].set(entryDict["Total duration of the experiment (hours): "]["var"].get()*60*60)
                entryDict["Maximum time between wheel events (seconds): "]["var"].set(entryDict["Total duration of the experiment (hours): "]["var"].get()*60*60)
                entryDict["Duration of each reward frame (seconds): "]["var"].set(entryDict["Total duration of the experiment (hours): "]["var"].get()*60*60)
                entryDict["Duration of pump \"on\" state (seconds): "]["var"].set(3)

                #Day 1 - Always show reward image and leave reward active - no wheel trigger needed
                if presetID == 1:
                    #Set image checkbox
                    cVar, rVar = imageBarDict["Solid"]["var"]
                    cVar.set(0)

                    #Change any defaults
                    entryDict["Minimum wheel revolutions for reward: "]["var"].set(0)
                    entryDict["Maximum wheel revolutions for reward: "]["var"].set(0)

            #On days 2 and 3 the number of wheel revolutions for a reward is constant
            if presetID >= 2 and presetID <= 3:
                entryDict["Minimum wheel revolutions for reward: "]["var"].set(25)
                entryDict["Maximum wheel revolutions for reward: "]["var"].set(entryDict["Minimum wheel revolutions for reward: "]["var"].get())

            if presetID == 3:
                entryDict["Maximum duration of reward state (seconds): "]["var"].set(30)

            #If Test is selected, show contrast controls, and reduce wheel reset time

            if presetID == 5:
                entryDict["Maximum time between wheel events (seconds): "]["var"].set(5)
                frameDict["contrast"].grid()
                entryDict["Maximum wheel revolutions for reward: "]["var"].set(50)

            if presetID == 6:
                entryDict["Maximum time between wheel events (seconds): "]["var"].set(5)
                frameDict["frequency"].grid()
                entryDict["Maximum wheel revolutions for reward: "]["var"].set(50)

            #Day 4 - Same as day 3, but control and reward intervals are randomized - default protocol
            else:
                pass

##################################################################################################################

        contrastDict["Calculated contrast step ratio: "]["entry"].config(state='disabled')
        testbox() #Make sure at least one image is selected

    def toggleGUI(state):
        nonlocal radioList
        nonlocal entryDict
        nonlocal imageBarDict

        #Inactivate entry boxes, radio buttons, and check boxes
        for key, value in entryDict.items():
            value["entry"].config(state=state)
        for key, value in imageBarDict.items():
            cChk, rChk = value["chk"]
            cChk.config(state=state)
            rChk.config(state=state)
        for b in radioList:
            b.config(state=state)

        #Switch button state
        if state == 'disabled':
            uploadButton.config(text="Cancel")
        else:
            uploadButton.config(text="Upload")
            loadPreset() #Setup GUI to match current preset

    mainWindow = Tk()
    mainWindow.title("Protocol generator...")
    gui = VerticalScrolledFrame(mainWindow, width=470, height=740)
    gui.pack(fill=BOTH, expand=True)

    #Initialize frame set
    gui.grid_columnconfigure(0, weight=1)
    frameList = ["entry", "contrast", "frequency", "check", "radio", "metadata", "button"]
    frameDict = {}
    for row in range(len(frameList)):
        frameDict[frameList[row]] = Frame(master=gui)
        frameDict[frameList[row]].grid(column=0, row=row, sticky=W+E)
    #frameDict["button"].grid(sticky=W+E) #Stretch button frame to width of window
    frameDict["contrast"].grid_remove() #Hide contrast panel on GUI initialization

    #Set default font to 12
    default_font = font.nametofont("TkDefaultFont")
    default_font.configure(size=12)
    gui.option_add("*Font", default_font)

    #Create set of entry boxes for entering in protocol
    frameDict["entry"].grid_columnconfigure(0, weight=1)
    rowList = list(entryDict.keys())
    for key, value in entryDict.items():
        label = Label(frameDict["entry"], text = key, anchor=W)
        label.grid(column=0, row=rowList.index(key), sticky=W)
        var = DoubleVar(frameDict["entry"])
        entry = Entry(frameDict["entry"], width=10, textvariable=var, justify=RIGHT, disabledforeground="BLACK", validate="focus", validatecommand=lambda: testEntry(False))
        entry.grid(column=1, row=rowList.index(key), sticky=E, pady=10, padx=(0,5))
        entryDict[key] = {"label": label, "var": var, "entry": entry}
    Separator(frameDict["entry"], orient=HORIZONTAL).grid(row=len(entryDict), columnspan=5, sticky="ew")

    #Create set of entry boxes for entering in contrast protocol
    frameDict["contrast"].grid_columnconfigure(0, weight=1)
    rowList = list(contrastDict.keys())
    for key, value in contrastDict.items():
        label = Label(frameDict["contrast"], text = key, anchor=W)
        label.grid(column=0, row=rowList.index(key), sticky=W)
        var = DoubleVar(frameDict["contrast"])
        entry = Entry(frameDict["contrast"], width=10, textvariable=var, justify=RIGHT, disabledforeground="BLACK", validate="focus", validatecommand=lambda: testEntry(False))
        entry.grid(column=1, row=rowList.index(key), sticky=E, pady=10, padx=(0,5))
        contrastDict[key] = {"label": label, "var": var, "entry": entry}
    Separator(frameDict["contrast"], orient=HORIZONTAL).grid(row=len(contrastDict), columnspan=5, sticky="ew")

    #Create set of entry boxes for entering in frequency protocol
    frameDict["frequency"].grid_columnconfigure(0, weight=1)
    rowList = list(frequencyDict.keys())
    for key, value in frequencyDict.items():
        label = Label(frameDict["frequency"], text = key, anchor=W)
        label.grid(column=0, row=rowList.index(key), sticky=W)
        var = DoubleVar(frameDict["frequency"])
        entry = Entry(frameDict["frequency"], width=10, textvariable=var, justify=RIGHT, disabledforeground="BLACK", validate="focus", validatecommand=lambda: testEntry(False))
        entry.grid(column=1, row=rowList.index(key), sticky=E, pady=10, padx=(0,5))
        frequencyDict[key] = {"label": label, "var": var, "entry": entry}
    Separator(frameDict["frequency"], orient=HORIZONTAL).grid(row=len(frequencyDict), columnspan=5, sticky="ew")


    #Create pair of check box bars to select preset images for control and reward
    row = rowList.index(key)+1
    controlImageLabel = Label(frameDict["check"], text = "Control images(s): ", anchor=W)
    controlImageLabel.grid(column=0, row=row, sticky=W, padx=(0,150))
    rewardImageLabel = Label(frameDict["check"], text = "Reward images(s): ", anchor=W)
    rewardImageLabel.grid(column=1, row=row, sticky=W)
    row += 1


    imageBarDict = {}
    for a in imageList:
        cVar = IntVar()
        cChk = Checkbutton(frameDict["check"], text=re.sub(r"_", " ", a), variable=cVar, command=testbox, disabledforeground="BLACK")
        cChk.grid(column=0, row=row, sticky=W)
        rVar = IntVar()
        rChk = Checkbutton(frameDict["check"], text=re.sub(r"_", " ", a), variable=rVar, command=testbox, disabledforeground="BLACK")
        rChk.grid(column=1, row=row, sticky=W)
        imageBarDict[a] = {"var": (cVar, rVar), "chk": (cChk, rChk)}
        row += 1

    #Create preset radio buttons
    presetLabel = Label(frameDict["radio"], text = "Select protocol preset: ")
    presetLabel.pack(side=TOP, anchor=W)
    presetVar = IntVar()
    presetVar.set(initialPreset) # initialize
    a=0
    for text, mode in presetList:
        b = Radiobutton(frameDict["radio"], text=text, variable=presetVar, value=mode, command=loadPreset)
        b.pack(side=LEFT)
        radioList[a] = b
        a += 1

    #Add text box with scroll bar for entering any metadata
    metadataBox = Text(frameDict["metadata"], height=4, width=47)
    metadataBox.pack(side=LEFT, padx=5, pady=5)
    metadataBox.insert(END, "Type metadata here...")
    textScroll = Scrollbar(frameDict["metadata"])
    textScroll.pack(side=RIGHT, padx=5, pady=5, fill=Y)
    textScroll.config(command=metadataBox.yview)
    metadataBox.config(yscrollcommand=textScroll.set)

    #Add upload button
    uploadButton = Button(frameDict["button"], text="Upload", command=lambda: testEntry(True)) #On click, check entries and upload if valid
    uploadButton.pack(side=RIGHT, anchor=E, padx=10, pady=10)
    statusLabel = Label(frameDict["button"], text = "Set protocol parameters and press \"Upload\"...")
    statusLabel.pack(side=LEFT, anchor=W)

    #Initialize to default preset
    loadPreset()

    gui.mainloop() #Blocks rest of code from executing - similar to while True with update loop

def uploadProtocol(frameDict, entryDict, contrastDict, frequencyDict, imageBarDict, metadataBox, statusLabel, killFlag, uploadButton, presetVar, presetList):
    global nCages

    def parseProtocol():
        nonlocal frameDict
        nonlocal entryDict
        nonlocal contrastDict
        nonlocal frequencyDict
        nonlocal imageBarDict
        nonlocal metadataBox
        nonlocal imageList
        nonlocal driveName

        controlList = []
        rewardList = []

        #Parse image sets
        for key, value in imageBarDict.items(): #Count number of active control and reward images
            cVar, rVar = value["var"]
            if cVar.get() == 1:
                controlList.append(key + ".png")
            if rVar.get() == 1:
                if frameDict["contrast"].grid_info(): #If contrast series is selected, generate a list of contrast images.
                    minContrast = contrastDict["Minimum contrast ratio (0-100): "]["var"].get()
                    maxContrast = contrastDict["Maximum contrast ratio (0-100): "]["var"].get()
                    nSteps = contrastDict["Number of contrast steps: "]["var"].get()
                    stepRatio = contrastDict["Calculated contrast step ratio: "]["var"].get()

                    for a in range(int(nSteps)):
                        contrast = maxContrast*(stepRatio**a)
                        imageName = key + "-contrast_" + str(round(contrast))
                        rewardList = [imageName + ".png"] + rewardList

                elif frameDict["frequency"].grid_info(): #If frequency series is selected, generate a list of frequency images.
                    minFreq = frequencyDict["Minimum pattern frequency (2-" + str(round(imageWidth/2)) + "): "]["var"].get()
                    maxFreq = frequencyDict["Maximum pattern frequency (2-" + str(round(imageWidth/2)) + "): "]["var"].get()
                    nSteps = frequencyDict["Number of frequency steps: "]["var"].get()
                    stepRatio = frequencyDict["Calculated frequency step ratio: "]["var"].get()

                    for a in range(int(nSteps)):
                        frequency = maxFreq*(stepRatio**a)
                        imageName = key + "-frequency_" + str(round(frequency))
                        rewardList = [imageName + ".png"] + rewardList
                else:
                    rewardList.append(key + ".png")
        presetID = presetVar.get()

        #Add negative control image to frequency and contrast sets
        if(presetID in (5,6)):
            rewardList.append("SolidReward-NegativeControl.png") #Add negative control to reward list
            contrastDict["Number of contrast steps: "]["var"].set(contrastDict["Number of contrast steps: "]["var"].get() + 1) #Add one to the number of reward images - needed for behavior protocol check ############################################################################################################################
            frequencyDict["Number of frequency steps: "]["var"].set(frequencyDict["Number of frequency steps: "]["var"].get() + 1)

        imageList = rewardList + controlList #generate a list of all unique images used in the protocol
        preset = presetVar.get()
        for k,v in presetList:
            if v == preset:
                preset = k

        #Build prtocol string
        protocolString = ("Experiment preset: " + preset + "\r\n" +
                        "USB drive ID: " + driveName + "\r\n" +
                        "Control image set: " + re.sub("\'", "", str(controlList)) + "\r\n" +
                        "Reward image set: " + re.sub("\'", "", str(rewardList)) + "\r\n")
        for key, value in entryDict.items():
            protocolString += key + str(value["var"].get()) + "\r\n"

        if frameDict["contrast"].grid_info(): #If contrast frame is active, add contrast data to protocol string
            for key, value in contrastDict.items():
                protocolString += key + str(value["var"].get()) + "\r\n"

        if frameDict["frequency"].grid_info(): #If frequency frame is active, add frequency data with contrast keys to protocol string - workaround for contrast specific checks in the behavior protocol
            for (f_key, f_value), (c_key, c_value) in zip(frequencyDict.items(), contrastDict.items()): #Iterate over two dictionaries at the same time: https://stackoverflow.com/questions/20736709/how-to-iterate-over-two-dictionaries-at-once-and-get-a-result-using-values-and-k
                protocolString += c_key + str(f_value["var"].get()) + "\r\n"####################################################################################################################################################################################################################################################################

        #Remove the +1 adjustment
        if(presetID in (5,6)):
            contrastDict["Number of contrast steps: "]["var"].set(contrastDict["Number of contrast steps: "]["var"].get() - 1) #Add one to the number of reward images - needed for behavior protocol check ############################################################################################################################
            frequencyDict["Number of frequency steps: "]["var"].set(frequencyDict["Number of frequency steps: "]["var"].get() - 1)

        protocolString += "Metadata: " + str(metadataBox.get("1.0", "end")) #"1.0" means read starting line 1 character 0, END means read to end and add newline (end-1c would remove the added newline) https://stackoverflow.com/questions/14824163/how-to-get-the-input-from-the-tkinter-text-box-widget

        return protocolString


    def findUSB():
        nonlocal statusLabel
        nonlocal cageList
        nonlocal cage
        nonlocal driveGroup
        nonlocal driveName
        nonlocal cageNum

        mountDir = None

        post_mount_locations = psutil.disk_partitions()
        pre_mount_locations = post_mount_locations #partition list prior to mounting drive
        error = False
        while True:
            if not killFlag.empty(): #Get kill flag if there is one in the queue - empty is blocking so check if there is a flag before getting
                if killFlag.get() == 0: #If cancel button is pressed, exit thread
                    return None
            post_mount_locations = psutil.disk_partitions()
            time.sleep(0.1)
            #print(str(len(post_mount_locations)) + " " + str(len(pre_mount_locations)))
            if not error and len(post_mount_locations) - len(pre_mount_locations) == 1: #If new partition is found, save file to new partition
                mountDir = list(set(post_mount_locations) - set(pre_mount_locations))[0].mountpoint #new disk partition is where usb is mounted
                statusLabel.config(text="USB drive found, files will be saved to: " + str(mountDir[:-1]))
                if os.name != 'posix':
                    driveName, _, _, _, _ = win32api.GetVolumeInformation(str(mountDir)) #Get name of mounted dri\\]=
                else:
                    driveName = mountDir.split('/')[-1]
                mountDir += '/'
                if re.match(r"^CAGE [1-len(cageList)][A-B]$", driveName): #Check that USB has valid name
                    cageNum = driveName[-2:-1]

                    if driveGroup is None:
                        driveGroup = driveName[-1:]
                    else:
                        if driveName[-1:] == driveGroup:
                            if driveName not in cageList: #Check that a protocol has not already been written for this cage
                                cageList[cage] = driveName
                                statusLabel.config(text="Protocol uploaded to: " + driveName + ", insert next drive...")
                                return mountDir
                            else:
                                statusLabel.config(text=driveName + " has already been uploaded.  Please choose a different drive.")
                                error = True
                        else:
                            statusLabel.config(text=driveName + " is not from group " + driveGroup + ".  Please choose a different drive.")
                            error = True
                else:
                    statusLabel.config(text=driveName + " is not a valid drive.  Please choose a different drive.")
                    error = True
            elif (not error and len(post_mount_locations) - len(pre_mount_locations) == -1) or (error and  len(post_mount_locations) - len(pre_mount_locations) == 0): #If partion was removed, thumb drive was removed so reset partition list
                statusLabel.config(text="USB drive removed, please insert USB drive...")
                pre_mount_locations = post_mount_locations #partition list prior to mounting drive
                error = False

    def convertContrast(contrast):
        nonlocal LUTdic

        def lutSearch(refContrast):
            nonlocal LUTdic
            nonlocal meanPower

            currentPowerDiff = 2*meanPower
            minPowerDiff = 2*meanPower
            index = None
            for a in range(len(LUTdic["Power"])):
                currentPowerDiff = abs(LUTdic["Power"][a] - (meanPower+refContrast))
                if(currentPowerDiff <= minPowerDiff):
                    minPowerDiff = currentPowerDiff
                    index = a

            return index

        #Find the pixel value that is equal in power to the mean of the 0 and 255 powers
        maxPower = LUTdic["Power"][len(LUTdic["Power"])-1]
        minPower = LUTdic["Power"][0]
        meanPower = (maxPower + minPower)/2
        maxContrast = maxPower-minPower

        meanIndex = lutSearch(0)

        #Find high intensity that is 1/2 contrast above mean
        halfContrast = maxContrast*(contrast/100)*0.5
        currentPowerDiff = 2*meanPower
        minPowerDiff = 2*meanPower
        highIndex = lutSearch(halfContrast)
        lowIndex = lutSearch(-1*halfContrast)

        return [(0,lowIndex,0), (0,highIndex,0)]

    def exportFiles(fileString, mountDir):
        nonlocal imageList
        nonlocal contrastDict
        nonlocal frequencyDict

        if mountDir is None: #If cancel button is pressed, exit thread
            return
        pfileName = mountDir + 'Protocol.txt'
        with open(pfileName, 'w+') as pfile: #write protocol specs to protocol file
            pfile.write(fileString)

        #Get contrast and frequency exponentiation parameters
        maxContrast = contrastDict["Maximum contrast ratio (0-100): "]["var"].get()
        contrastStepRatio = contrastDict["Calculated contrast step ratio: "]["var"].get()
        contrastStepCount = contrastDict["Number of contrast steps: "]["var"].get()

        maxFrequency = frequencyDict["Maximum pattern frequency (2-" + str(round(imageWidth/2)) + "): "]["var"].get()
        frequencyStepRatio = frequencyDict["Calculated frequency step ratio: "]["var"].get()
        frequencyStepCount = frequencyDict["Number of frequency steps: "]["var"].get()

        #Generate images
        imageDir = mountDir + "images/"
        highInt = (0,255,0)
        lowInt = (0,0,0)
        frequency = entryDict["Pattern frequency for images: "]["var"].get()

        for image in imageList:
            if("contrast" in image.lower()): # if image is contrast type, get root type and contrast settings
                contrastStepCount -= 1
                contrast = maxContrast*(contrastStepRatio**contrastStepCount)
                lowInt, highInt = convertContrast(contrast)

            elif("frequency" in image.lower()): # if image is frequency type, get root type and frequency settings
                frequencyStepCount -= 1
                frequency = round((maxFrequency*(frequencyStepRatio**frequencyStepCount)))

            imageFile = drawImage(image, frequency, lowInt, highInt)

            try:
                imageFile.save(imageDir + image, format="PNG")
            except:
                os.mkdir(imageDir)
                imageFile.save(imageDir + image, format="PNG")

    def importLUT():
        nonlocal cageNum

        if mountDir is None: #If cancel button is pressed, exit thread
            return False

        #Find the LUT file on the thumb drive
        LUTlist = glob.glob(mountDir + "Calibration LUT - 201[0-9]-[0-1][0-9]-[0-3][0-9] - Monitor [1-" + str(len(cageList)) + "].txt")

        if(len(LUTlist) == 0):
            statusLabel.config(text="ERROR: Calibration LUT is missing from this drive.")
            return False
        elif(len(LUTlist) > 1):
            statusLabel.config(text="ERROR: There is more than one calibration LUT on this drive.")
            return False
        else:
            #Confirm that LUTnum matches cageNum
            LUTnum = LUTlist[0][-5:-4]

            if cageNum == LUTnum:

                with open(LUTlist[0]) as f:
                    rawLUT = f.readlines()

                #Parse the LUT
                dummy = rawLUT.pop(0) #Remove the header line from the LUT
                LUTdic = {"Color": [None]*len(rawLUT), "Power": [None]*len(rawLUT)}
                for a in range(len(rawLUT)):
                    try:
                        #Parse color tuple
                        color = re.search(r"^\(([0-9]{1,3}, ){2}[0-9]{1,3}\)", rawLUT[a]).group(0) #Find color tuple substring in LUT
                        color = tuple(map(int, color[1:-1].split(', '))) #Convert to tuple: https://bytes.com/topic/python/answers/45526-convert-string-tuple
                        LUTdic["Color"][a] = color

                        #Parse power float
                        #Float search string from: https://stackoverflow.com/questions/4703390/how-to-extract-a-floating-number-from-a-string
                        numeric_const_pattern = ',[-+]? (?: (?: \d* \. \d+ ) | (?: \d+ \.? ) )(?: [Ee] [+-]? \d+ ) ?,\n'
                        rx = re.compile(numeric_const_pattern, re.VERBOSE)
                        LUTdic["Power"][a] = float(rx.search(rawLUT[a]).group(0)[1:-1]) #Convert string to float

                    except:
                        statusLabel.config(text="ERROR: invalid syntax on line " + str(a+2) + ", \"" + rawLUT[a])
                        return False
            else:
                statusLabel.config(text="ERROR: LUT number: " + str(LUTnum) + " and cage number: " + str(cageNum) + " don't match. Press \"Cancel\"")
                return False
        return LUTdic


    def drawImage(mode, freq, foreground, background):
        global imageWidth
        global imageHeight

        #Make a solid image that has the same average power of the 255 and 0 intensities
        if mode.startswith("Solid"):
            background, foreground = convertContrast(0)

        image = Image.new("RGB", (imageWidth, imageHeight), color=background) #Create and image filled with background color
        drawObject = ImageDraw.Draw(image) #Create drawing context

        #Create checkerboard as default starting pattern
        squareWidth = imageWidth/(2*freq)
        squareHeight = squareWidth

        x0 = 0
        y0 = 0
        drawSquare = True
        row = 0
        column = 0

        while y0 < imageHeight:
            y1 = round(squareHeight*(row+1)) #Calculate new position of bottom of square
            x0 = 0 #Reset x0 position
            column = 0
            drawSquare = not drawSquare #Shift phase of draw square to enable checkerboard pattern
            while x0 < imageWidth:
                x1 = round(squareWidth*(column+1)) #Calculate new position of bottom of square
                #Draw square pattern based on mode
                if mode.startswith("Horizontal_Stripes"): #Draw horizontal lines
                    if(row%2 == 0):
                        drawSquare = False
                    else:
                        drawSquare = True
                elif mode.startswith("Vertical_Stripes"): #Draw vertical lines
                    if(column%2 == 0):
                        drawSquare = False
                    else:
                        drawSquare = True
                elif mode.startswith("Solid"): #Leave image blank - background only
                    drawSquare = False
                else: #By default, draw checkerboard pattern
                    drawSquare = not drawSquare
                if drawSquare:
                    drawObject.rectangle([x0, y0, x1, y1], fill=foreground, outline=None, width=0)
                #print(str([x0, y0, x1, y1]))
                x0 = x1 #Increment x0 position
                column += 1

            y0 = y1 #Increment y0 position
            #print(str(row) + " " + str(column) + " " + str(count))
            row += 1
        return image


    cageList = [None]*nCages
    cageNum = None
    driveGroup = None #Whether uploading to set A or set B
    driveName = None #Name of current USB drive
    statusLabel.config(text="Please insert USB drive...")
    imageList = None

    for cage in range(len(cageList)): #Export once for each cage
        mountDir = findUSB()
        if mountDir is None:
            return
        LUTdic = importLUT()
        if LUTdic:
            protocolString = parseProtocol()
            exportFiles(protocolString, mountDir)
        else:
            while(killFlag.get() is not 0):
                time.sleep(0.1)
            return

    time.sleep(2)
    statusLabel.config(text="Protocol upload complete!")
    uploadButton.config(text="Quit")

if __name__ == '__main__':
    buildGUI()


