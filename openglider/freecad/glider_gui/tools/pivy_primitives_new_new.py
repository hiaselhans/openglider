from pivy import coin

COLORS = {
    "black": (0, 0, 0),
    "white": (1., 1., 1.),
    "grey": (0.5, 0.5, 0.5),
    "red": (1., 0., 0.),
    "blue": (0., 0., 1.),
    "green": (0., 1., 1.),
    "yellow": (0., 1., 0.)
}

COL_STD = COLORS["black"]
COL_OVR = COLORS["red"]
COL_SEL = COLORS["yellow"]



# changes:
# make a container for all the points instead of classmethode of the 3d objects
# a container is a SoSeperator and has a over_object list and a selected_obj list


class Object3D(coin.SoSeparator):
    """addiditional to coin this list stores all the geometry"""
    # point, line, polygon
    def __init__(self, dynamic=False):
        super(Object3D, self).__init__()
        self.data = coin.SoCoordinate3()
        self.color = coin.SoMaterial()
        self.color.diffuseColor = COL_STD
        self.addChild(self.color)
        self.addChild(self.data)
        self.start_pos = None
        self.dynamic = dynamic
        self.on_drag = []
        self.on_drag_release = []
        self.on_drag_start = []

    @property
    def points(self):
        return self.data.point.getValues()

    @points.setter
    def points(self, points):
        self.data.point.setValue(0, 0, 0)
        self.data.point.setValues(0, len(points), points)

    def set_mouse_over(self):
        self.color.diffuseColor = COL_OVR

    def unset_mouse_over(self):
        self.color.diffuseColor = COL_STD

    def select(self):
        self.color.diffuseColor = COL_SEL

    def unselect(self):
        self.color.diffuseColor = COL_STD

    def drag(self, mouse_coords, fact=1.):
        pts = self.points
        for i in pts:
            i[0] += mouse_coords[0] * fact
            i[1] += mouse_coords[1] * fact
            i[2] += mouse_coords[2] * fact
        self.points = pts
        for i in self.on_drag:
            i()

    @property
    def drag_objects(self):
        return [self]

    @property
    def delete(self):
        self.objects.remove(self)
        self.removeAllChildren()


class Marker(Object3D):
    def __init__(self, points, dynamic=False):
        super(Marker, self).__init__(dynamic=dynamic)
        self.marker = coin.SoMarkerSet()
        self.marker.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_9_9
        self.points = points
        self.addChild(self.marker)


class Line(Object3D):
    def __init__(self, points, dynamic=False):
        super(Line, self).__init__(dynamic)
        self.line = coin.SoLineSet()
        self.points = points
        self.addChild(self.line)


class Container(coin.SoSeparator):
    def __init__(self):
        super(Container, self).__init__()
        self.objects = []
        self.select_object = []
        self.drag_objects = []
        self.over_object = None
        self.start_pos = None
        self.view = None

    def addChild(self, child):
        super(Container, self).addChild(child)
        if child.dynamic:
            self.objects.append(child)

    def addChildren(self, children):
        for i in children:
            self.addChild(i)

    def Highlight(self, obj):
        if self.over_object:
            self.over_object.unset_mouse_over()
        self.over_object = obj
        if self.over_object:
            self.over_object.set_mouse_over()
        self.ColorSelected()

    def Select(self, obj, multi=False):
        if not multi:
            for o in self.select_object:
                o.unselect()
            self.select_object = []
        if obj:
            if obj in self.select_object:
                self.select_object.remove(obj)
            else:
                self.select_object.append(obj)
        self.ColorSelected()

    def ColorSelected(self):
        for obj in self.select_object:
            obj.select()

    def cursor_pos(self, event):
        pos = event.getPosition()
        return self.view.getPoint(*pos)

    def mouse_over_cb(self, event_callback):
        event = event_callback.getEvent()
        pos = event.getPosition()
        obj = self.SendRay(pos)
        self.Highlight(obj)

    def SendRay(self, mouse_pos):
        """sends a ray trough the scene and return the nearest entity"""
        render_manager = self.view.getViewer().getSoRenderManager()
        ray_pick = coin.SoRayPickAction(render_manager.getViewportRegion())
        ray_pick.setPoint(coin.SbVec2s(*mouse_pos))
        ray_pick.setRadius(10)
        ray_pick.setPickAll(True)
        ray_pick.apply(render_manager.getSceneGraph())
        picked_point = ray_pick.getPickedPointList()
        return self.ObjById(picked_point)

    def ObjById(self, picked_point):
        for point in picked_point:
            path = point.getPath()
            length = path.getLength()
            point = path.getNode(length - 2)
            point = filter(
                lambda ctrl: ctrl.getNodeId() == point.getNodeId(),
                self.objects)
            if point != []:
                return point[0]
        return None

    def select_cb(self, event_callback):
        event = event_callback.getEvent()
        if event.getState() == coin.SoMouseButtonEvent.DOWN:
            pos = event.getPosition()
            obj = self.SendRay(pos)
            self.Select(obj, event.wasCtrlDown())

    def drag_cb(self, event_callback):
        event = event_callback.getEvent()
        if (type(event) == coin.SoMouseButtonEvent and
            event.getState() == coin.SoMouseButtonEvent.DOWN):
                self.register(self.view)
                self.view.removeEventCallbackPivy(
                coin.SoEvent.getClassTypeId(), self.drag)
                self.start_pos = None
        elif type(event) == coin.SoLocation2Event:
            fact = 0.3 if event.wasShiftDown() else 1.
            diff = self.cursor_pos(event) - self.start_pos
            self.start_pos = self.cursor_pos(event)
            for obj in self.drag_objects:
                obj.drag(diff, fact)
        #get the mouse position
        #call the drag function of the selected entities
        pass

    def grab_cb(self, event_callback):
        # press g to move an entity
        # later let the user select more entities...
        event = event_callback.getEvent()
        # get all drag objects, every selected object can add some drag objects
        # but the eventhandler is not allowed to call the drag twice on an object
        if event.getKey() == ord("g"):
            self.drag_objects = []
            for i in self.select_object:
                for j in i.drag_objects:
                    self.drag_objects.append(j)
            self.drag_objects = set(self.drag_objects)
            # check if something is selected
            if self.drag_objects:
                # first delete the selection_cb, and higlight_cb
                self.unregister()
                # now add a callback that calls the dragfunction of the selected entites
                self.start_pos = self.cursor_pos(event)
                self.drag = self.view.addEventCallbackPivy(
                    coin.SoEvent.getClassTypeId(), self.drag_cb)

    def register(self, view):
        self.view = view
        self.mouse_over = self.view.addEventCallbackPivy(
            coin.SoLocation2Event.getClassTypeId(), self.mouse_over_cb)
        self.select = self.view.addEventCallbackPivy(
            coin.SoMouseButtonEvent.getClassTypeId(), self.select_cb)
        self.grab = self.view.addEventCallbackPivy(
            coin.SoKeyboardEvent.getClassTypeId(), self.grab_cb)

    def unregister(self):
        self.view.removeEventCallbackPivy(
            coin.SoLocation2Event.getClassTypeId(), self.mouse_over)
        self.view.removeEventCallbackPivy(
            coin.SoMouseButtonEvent.getClassTypeId(), self.select)
        self.view.removeEventCallbackPivy(
            coin.SoKeyboardEvent.getClassTypeId(), self.grab)

    def removeAllChildren(self):
        print("i was called")
        for i in self.objects:
            i.delete()
        self.objects = []
        super(Container, self).removeAllChildren()


from openglider.utils.bezier import BezierCurve, SymmetricBezier
from openglider.vector import mirror_x
import numpy


class Spline(Container):
    def __init__(self, points, dynamic=False):
        super(Spline, self).__init__()
        self.bez = BezierCurve(points)
        for i in points:
            self.addChild(Marker([i], dynamic=dynamic))
        self.line = Line(self.bez.get_sequence(50), dynamic=False)
        super(Spline, self).addChild(self.line)

    def addChild(self, child):
        if isinstance(child, Marker):
            child.on_drag.append(self.update_spline)
            super(Spline, self).addChild(child)
        else:
            print("Spline Children have to be maekrers")

    @property
    def marker_points(self):
        return [obj.points[0] for obj in self.objects]

    def update_spline(self):
        self.bez.controlpoints = self.marker_points
        self.line.points = self.bez.get_sequence(50)


class SymmetricSpline(Container):
    def __init__(self, points, dynamic=False):
        super(SymmetricSpline, self).__init__()
        self.bez = SymmetricBezier(points, mirror_x)
        for i in points:
            self.addChild(Marker([i], dynamic=dynamic))
        self.line = Line(self.bez.get_sequence(50), dynamic=False)
        super(SymmetricSpline, self).addChild(self.line)

    def addChild(self, child):
        if isinstance(child, Marker):
            child.on_drag.append(self.update_spline)
            super(SymmetricSpline, self).addChild(child)
        else:
            print("Spline Children have to be maekrers")

    @property
    def marker_points(self):
        return [obj.points[0] for obj in self.objects]

    def update_spline(self):
        self.bez.controlpoints = self.marker_points
        self.line.points = self.bez.get_sequence(50)

if __name__ == "__main__":
    import FreeCADGui as Gui
    s1 = Spline([[0,0,0],[1,1,1],[3,3,3]], dynamic=True)
    Gui.ActiveDocument.ActiveView.getSceneGraph().addChild(s1)
    s1.register(Gui.ActiveDocument.ActiveView)