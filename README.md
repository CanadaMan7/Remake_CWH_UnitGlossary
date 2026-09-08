# Remake_CWH_UnitGlossary
All credit to Ripoblus, who created the original for FFT and graciously allowed me to rehost this. My sincere thanks.

Provided Instructions are:
"Alright, I've uploaded code to the github. It's a bit messy currently because the output html pages get written to the same path as the scripts - this was a temporary step on my part to get GitHub to recognize the splash page.
https://github.com/ripoblus858-droid/eaw-unit-glossary

The readme has a complete step-by-step guide: for CWH, in the run_glossary.bat file (step 4) just remove the mod path for FFT, and redirect the projectiles.xml and translationsmanifest.xml paths to that of CWH.

Briefly, the procedure is: 
     
The in-game tga icons need to be converted to png to be rendered correctly in html. First, use MTD Editor (https://modtools.petrolution.net/tools/MtdEditor) to mass extract tga icons into a .tga folder. Then, run the Python script convert_icons.py to convert them to a folder of pngs. (In the following step, only pngs rendered on the web pages are kept, and the remaining are moved to an "unused" folder and can be discarded.)
Generate all web pages by running run_glossary.bat, but first, open the file and take a look at the parameter specifications. It simply runs a Python script, but it takes as input a half dozen or so .txt files. These files optionally specify all sorts of manual refinements to the xml entries to improve presentation of the web pages. In practice, I end up running the .bat multiple times, each time inspecting a few entries for errors, and return to these parameter files for modifications as needed."
