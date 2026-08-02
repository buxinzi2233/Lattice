import QtQuick

Item {
    id: icon

    property string name: "plus"
    property color color: "#f7f8f4"
    property real opticalX: 0
    property real opticalY: 0
    property real strokeWidth: 1.8
    readonly property real fixedOpticalX: name === "play" ? 0.5 : name === "edit" ? 0.25 : 0
    readonly property real fixedOpticalY: name === "external" ? 0.25 : name === "download" ? 0.25 : 0

    implicitWidth: 24
    implicitHeight: 24
    width: 24
    height: 24

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.translate(12 + icon.opticalX + icon.fixedOpticalX, 12 + icon.opticalY + icon.fixedOpticalY)
            ctx.strokeStyle = icon.color
            ctx.fillStyle = icon.color
            ctx.lineWidth = icon.strokeWidth
            ctx.lineCap = "square"
            ctx.lineJoin = "miter"
            function line(x1, y1, x2, y2) {
                ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke()
            }
            function chevron(dx) {
                ctx.beginPath(); ctx.moveTo(-4, -6); ctx.lineTo(2, 0); ctx.lineTo(-4, 6); ctx.stroke()
                ctx.beginPath(); ctx.moveTo(2, -6); ctx.lineTo(8, 0); ctx.lineTo(2, 6); ctx.stroke()
            }
            switch (icon.name) {
            case "plus": line(-6, 0, 6, 0); line(0, -6, 0, 6); break
            case "minus": line(-6, 0, 6, 0); break
            case "close": line(-6, -6, 6, 6); line(6, -6, -6, 6); break
            case "refresh":
                ctx.beginPath(); ctx.arc(0, 0, 7, -0.65, 4.55); ctx.stroke()
                ctx.beginPath(); ctx.moveTo(6, -6); ctx.lineTo(7, 0); ctx.lineTo(1, -1); ctx.stroke(); break
            case "home":
                ctx.beginPath(); ctx.moveTo(-8, -1); ctx.lineTo(0, -8); ctx.lineTo(8, -1); ctx.lineTo(8, 8); ctx.lineTo(-8, 8); ctx.closePath(); ctx.stroke()
                line(-2, 8, -2, 2); line(-2, 2, 3, 2); line(3, 2, 3, 8); break
            case "folder":
                ctx.beginPath(); ctx.moveTo(-8, -5); ctx.lineTo(-2, -5); ctx.lineTo(0, -2); ctx.lineTo(8, -2); ctx.lineTo(8, 7); ctx.lineTo(-8, 7); ctx.closePath(); ctx.stroke(); break
            case "download": line(0, -8, 0, 4); line(-4, 0, 0, 4); line(4, 0, 0, 4); line(-7, 8, 7, 8); break
            case "stop": ctx.fillRect(-6, -6, 12, 12); break
            case "play": ctx.beginPath(); ctx.moveTo(-4, -7); ctx.lineTo(7, 0); ctx.lineTo(-4, 7); ctx.closePath(); ctx.fill(); break
            case "edit": ctx.beginPath(); ctx.moveTo(-7, 6); ctx.lineTo(-5, 1); ctx.lineTo(5, -9); ctx.lineTo(9, -5); ctx.lineTo(-1, 5); ctx.closePath(); ctx.stroke(); line(-6, 6, -1, 5); break
            case "external": line(-2, 7, -7, 7); line(-7, 7, -7, -6); line(-7, -6, 2, -6); line(1, -8, 7, -8); line(7, -8, 7, -2); line(7, -8, -1, -1); break
            case "clear": ctx.beginPath(); ctx.moveTo(-5, -7); ctx.lineTo(5, -7); ctx.moveTo(-3, -7); ctx.lineTo(-3, 7); ctx.moveTo(3, -7); ctx.lineTo(3, 7); ctx.moveTo(-7, 8); ctx.lineTo(7, 8); ctx.stroke(); break
            case "pause": line(-3, -7, -3, 7); line(3, -7, 3, 7); break
            case "collapse": line(-6, -2, 0, 4); line(0, 4, 6, -2); break
            case "expand": line(-6, 2, 0, -4); line(0, -4, 6, 2); break
            case "drag": line(-5, -7, 5, -7); line(-5, 0, 5, 0); line(-5, 7, 5, 7); break
            case "settings": ctx.beginPath(); ctx.rect(-6, -6, 12, 12); ctx.stroke(); ctx.beginPath(); ctx.arc(0, 0, 3, 0, Math.PI * 2); ctx.stroke(); break
            case "type": ctx.font = "bold 9px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("Aa", 0, 0); break
            case "info": ctx.beginPath(); ctx.arc(0, 0, 8, 0, Math.PI * 2); ctx.stroke(); line(0, -2, 0, 6); ctx.fillRect(-1, -6, 2, 2); break
            case "arrow": line(-7, 0, 6, 0); line(1, -5, 6, 0); line(1, 5, 6, 0); break
            case "chevrons": chevron(0); break
            default: ctx.fillRect(-1, -1, 2, 2)
            }
        }
    }

    onNameChanged: canvas.requestPaint()
    onColorChanged: canvas.requestPaint()
    onOpticalXChanged: canvas.requestPaint()
    onOpticalYChanged: canvas.requestPaint()
}
