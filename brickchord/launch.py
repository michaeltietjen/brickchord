# Brickchord bootstrap: find NumPy and pygame (bundled or system), then start.
import os, sys, traceback
APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
print("python", sys.version.split()[0], sys.executable, flush=True)
try:
    import vendor
    vendor.setup(need_pygame=True)
    import main
    main.main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    sys.exit(1)
