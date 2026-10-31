# Brickchord bootstrap: use the bundled ARM64 NumPy, KNULLI's system pygame.
import os, sys, traceback
APP = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
vendor = os.path.join(APP, "_vendor")
if os.path.isdir(vendor):
    sys.path.insert(0, vendor)
sys.path.insert(0, APP)
try:
    import main
    main.main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    sys.exit(1)
