import sys
import os
from gogstash.main import main
if __name__ == "__main__":
    frozen = getattr(sys, 'frozen', False)
    on_linux = sys.platform.startswith('linux')
    if frozen and on_linux:
        original = os.environ.get('LD_LIBRARY_PATH_ORIG')
        if original:
            os.environ['LD_LIBRARY_PATH'] = original
        else:
            os.environ.pop('LD_LIBRARY_PATH', None)
        os.environ.pop('QT_PLUGIN_PATH', None)
        os.environ.pop('QML2_IMPORT_PATH', None)
    main()
