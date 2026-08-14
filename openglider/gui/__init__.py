#!/bin/env python
import os
import sys

os.environ["FORCE_QT_API"] = "pyside6"
os.environ["QT_API"] = "pyside6"

if sys.platform.startswith("linux"):
    platform_override = os.environ.get("OPENGLIDER_QT_PLATFORM")
    if platform_override:
        os.environ["QT_QPA_PLATFORM"] = platform_override


def start_main_window() -> None:
    from openglider.gui.app import GliderApp
    from openglider.gui.qt import QtCore, QtGui, QtWidgets

    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts,
        True
    )
    if sys.platform == "darwin":
        QtWidgets.QApplication.setAttribute(
            QtCore.Qt.ApplicationAttribute.AA_UseDesktopOpenGL,
            True
        )
    elif sys.platform.startswith("linux"):
        QtGui.QGuiApplication.setDesktopFileName("openglider")

    app = GliderApp(sys.argv)

    #app.tracker = tracker


    if sys.gettrace() != None:
        app.debug = True


    #og_dir = os.path.dirname(os.path.dirname(openglider.__file__))
    #filename = os.path.join(og_dir, "tests/common/demokite.ods")
    
    #if os.path.isfile(filename):
    #    print("loading {}".format(filename))

        #loop = asyncio.get_event_loop()

        #loop.run_until_complete(app.main_window.load_glider(filename))
        #asyncio.create_task()
        
    app.run()



    # cleanup
    #for task in app.task_queue.tasks:
    #    task.stop()

    #os.killpg(0, signal.SIGKILL)
    app.state.clean()
    return


if __name__ == '__main__':
    start_main_window()