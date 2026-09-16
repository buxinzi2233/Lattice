import QtQuick
import ".."

Item {
    id: icon

    property string name: "plus"
    property color color: Theme.white
    property real opticalX: 0
    property real opticalY: 0
    property real strokeWidth: 1.8

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
            if (width <= 0 || height <= 0)
                return

            // Match an SVG 24x24 viewBox with xMidYMid meet scaling.
            var scale = Math.min(width, height) / 24
            ctx.translate(width / 2 + icon.opticalX, height / 2 + icon.opticalY)
            ctx.scale(scale, scale)
            ctx.translate(-12, -12)
            ctx.strokeStyle = icon.color
            ctx.fillStyle = icon.color
            ctx.lineWidth = icon.strokeWidth
            ctx.lineCap = "round"
            ctx.lineJoin = "round"

            function line(x1, y1, x2, y2) {
                ctx.beginPath()
                ctx.moveTo(x1, y1)
                ctx.lineTo(x2, y2)
                ctx.stroke()
            }

            function polyline(points, closePath) {
                ctx.beginPath()
                ctx.moveTo(points[0], points[1])
                for (var index = 2; index < points.length; index += 2)
                    ctx.lineTo(points[index], points[index + 1])
                if (closePath)
                    ctx.closePath()
                ctx.stroke()
            }

            function circle(x, y, radius) {
                ctx.beginPath()
                ctx.arc(x, y, radius, 0, Math.PI * 2)
                ctx.stroke()
            }

            function roundedRect(x, y, boxWidth, boxHeight, radius) {
                ctx.beginPath()
                ctx.moveTo(x + radius, y)
                ctx.lineTo(x + boxWidth - radius, y)
                ctx.quadraticCurveTo(x + boxWidth, y, x + boxWidth, y + radius)
                ctx.lineTo(x + boxWidth, y + boxHeight - radius)
                ctx.quadraticCurveTo(x + boxWidth, y + boxHeight, x + boxWidth - radius, y + boxHeight)
                ctx.lineTo(x + radius, y + boxHeight)
                ctx.quadraticCurveTo(x, y + boxHeight, x, y + boxHeight - radius)
                ctx.lineTo(x, y + radius)
                ctx.quadraticCurveTo(x, y, x + radius, y)
                ctx.closePath()
                ctx.stroke()
            }

            switch (icon.name) {
            case "plus":
                line(5, 12, 19, 12)
                line(12, 5, 12, 19)
                break
            case "minus":
                line(5, 12, 19, 12)
                break
            case "close":
                line(18, 6, 6, 18)
                line(6, 6, 18, 18)
                break
            case "refresh":
                ctx.beginPath()
                ctx.arc(12, 12, 8.1, -0.124, -2.761, true)
                ctx.stroke()
                polyline([4, 4, 4, 9, 9, 9], false)
                ctx.beginPath()
                ctx.arc(12, 12, 8.1, 3.017, 0.381, true)
                ctx.stroke()
                polyline([20, 20, 20, 15, 15, 15], false)
                break
            case "home":
                polyline([4, 11, 12, 4, 20, 11, 20, 20, 4, 20], true)
                polyline([10, 20, 10, 14, 15, 14, 15, 20], false)
                break
            case "folder":
                ctx.beginPath()
                ctx.moveTo(6, 14)
                ctx.lineTo(7.5, 11.1)
                ctx.quadraticCurveTo(8.1, 10, 9.24, 10)
                ctx.lineTo(20, 10)
                ctx.quadraticCurveTo(22.5, 10, 21.94, 12.5)
                ctx.lineTo(20.4, 18.5)
                ctx.quadraticCurveTo(20, 20, 18.47, 20)
                ctx.lineTo(5, 20)
                ctx.quadraticCurveTo(3, 20, 3, 18)
                ctx.lineTo(3, 5)
                ctx.quadraticCurveTo(3, 3, 5, 3)
                ctx.lineTo(8.9, 3)
                ctx.quadraticCurveTo(10, 3, 10.59, 3.9)
                ctx.lineTo(11.4, 5.1)
                ctx.quadraticCurveTo(12, 6, 13.07, 6)
                ctx.lineTo(18, 6)
                ctx.quadraticCurveTo(20, 6, 20, 8)
                ctx.lineTo(20, 10)
                ctx.stroke()
                break
            case "search":
                circle(11, 11, 8)
                line(16.7, 16.7, 21, 21)
                break
            case "upload":
                ctx.beginPath()
                ctx.moveTo(21, 15)
                ctx.lineTo(21, 19)
                ctx.quadraticCurveTo(21, 21, 19, 21)
                ctx.lineTo(5, 21)
                ctx.quadraticCurveTo(3, 21, 3, 19)
                ctx.lineTo(3, 15)
                ctx.stroke()
                polyline([17, 8, 12, 3, 7, 8], false)
                line(12, 3, 12, 15)
                break
            case "download":
                line(12, 3, 12, 15)
                polyline([7, 10, 12, 15, 17, 10], false)
                line(5, 21, 19, 21)
                break
            case "power":
                line(12, 2, 12, 12)
                ctx.beginPath()
                ctx.arc(12, 13, 9, -0.79, -2.35, false)
                ctx.stroke()
                break
            case "stop":
                roundedRect(5, 5, 14, 14, 1)
                break
            case "play":
                polyline([6, 3, 20, 12, 6, 21], true)
                break
            case "edit":
                line(12, 20, 21, 20)
                ctx.beginPath()
                ctx.moveTo(16.5, 3.5)
                ctx.bezierCurveTo(17.32, 2.68, 18.68, 2.68, 19.5, 3.5)
                ctx.bezierCurveTo(20.32, 4.32, 20.32, 5.68, 19.5, 6.5)
                ctx.lineTo(7, 19)
                ctx.lineTo(3, 20)
                ctx.lineTo(4, 16)
                ctx.closePath()
                ctx.stroke()
                break
            case "external":
                polyline([15, 3, 21, 3, 21, 9], false)
                line(10, 14, 21, 3)
                ctx.beginPath()
                ctx.moveTo(18, 13)
                ctx.lineTo(18, 19)
                ctx.quadraticCurveTo(18, 21, 16, 21)
                ctx.lineTo(5, 21)
                ctx.quadraticCurveTo(3, 21, 3, 19)
                ctx.lineTo(3, 8)
                ctx.quadraticCurveTo(3, 6, 5, 6)
                ctx.lineTo(11, 6)
                ctx.stroke()
                break
            case "copy":
                roundedRect(8, 8, 13, 13, 2)
                ctx.beginPath()
                ctx.moveTo(16, 8)
                ctx.lineTo(16, 6)
                ctx.quadraticCurveTo(16, 4, 14, 4)
                ctx.lineTo(6, 4)
                ctx.quadraticCurveTo(4, 4, 4, 6)
                ctx.lineTo(4, 14)
                ctx.quadraticCurveTo(4, 16, 6, 16)
                ctx.lineTo(8, 16)
                ctx.stroke()
                break
            case "clear":
                ctx.beginPath()
                ctx.moveTo(7, 21)
                ctx.lineTo(3, 17)
                ctx.lineTo(12, 4)
                ctx.bezierCurveTo(12.9, 2.7, 14.7, 2.5, 15.7, 3.5)
                ctx.lineTo(20.5, 8.3)
                ctx.bezierCurveTo(21.5, 9.3, 21.3, 11.1, 20, 12)
                ctx.lineTo(7, 21)
                ctx.closePath()
                ctx.stroke()
                line(14, 6, 21, 13)
                line(5, 19, 21, 19)
                break
            case "pause":
                line(8, 5, 8, 19)
                line(16, 5, 16, 19)
                break
            case "collapse":
                polyline([6, 9, 12, 15, 18, 9], false)
                break
            case "expand":
                polyline([6, 15, 12, 9, 18, 15], false)
                break
            case "drag":
                circle(9, 5, 1)
                circle(9, 12, 1)
                circle(9, 19, 1)
                circle(15, 5, 1)
                circle(15, 12, 1)
                circle(15, 19, 1)
                break
            case "check":
                polyline([20, 6, 9, 17, 4, 12], false)
                break
            case "settings":
                roundedRect(6, 6, 12, 12, 0)
                circle(12, 12, 3)
                break
            case "type":
                ctx.font = "bold 9px sans-serif"
                ctx.textAlign = "center"
                ctx.textBaseline = "middle"
                ctx.fillText("Aa", 12, 12)
                break
            case "info":
                circle(12, 12, 8)
                line(12, 10, 12, 18)
                ctx.fillRect(11, 6, 2, 2)
                break
            case "arrow":
                line(5, 12, 18, 12)
                polyline([13, 7, 18, 12, 13, 17], false)
                break
            case "chevrons":
                polyline([4, 6, 10, 12, 4, 18], false)
                polyline([10, 6, 16, 12, 10, 18], false)
                break
            default:
                ctx.fillRect(11, 11, 2, 2)
            }
        }
    }

    onNameChanged: canvas.requestPaint()
    onColorChanged: canvas.requestPaint()
    onOpticalXChanged: canvas.requestPaint()
    onOpticalYChanged: canvas.requestPaint()
    onStrokeWidthChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
}
