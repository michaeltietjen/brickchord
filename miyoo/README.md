# Brickchord on the Miyoo Mini (Onion OS): first step

There is no Miyoo Mini build of Brickchord yet. The apps need Python 3 with NumPy,
and Onion OS doesn't come with them (PortMaster doesn't run on Onion either), so
before building one we need to know what your device has.

**Brick Probe** is a tiny Onion app that checks. It changes nothing on the device;
it only writes a report.

1. Download `BrickProbe-MiyooMini.zip` from the
   [miyoo-probe release](https://github.com/michaeltietjen/brickchord/releases/tag/miyoo-probe).
2. Unzip it to the root of the SD card (it goes into the `App` folder).
3. On the Miyoo, open **Apps** and run **Brick Probe**. It finishes at once.
4. Put the SD card in a computer and send `brickprobe.txt` (in the root of the card),
   in a GitHub issue or however you reached us.

With that report we can tell whether a test build of Brickchord can run on the Miyoo Mini,
and make one for you to try.
