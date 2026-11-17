import AppKit

let target = CommandLine.arguments[1]
let size: CGFloat = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
NSColor(calibratedRed: 0.98, green: 0.975, blue: 0.96, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: size, height: size), xRadius: 224, yRadius: 224).fill()
NSColor(calibratedRed: 1, green: 0.39, blue: 0.08, alpha: 1).setFill()
let blob = NSBezierPath()
for index in 0...160 {
    let angle = CGFloat(index) * .pi * 2 / 160
    let radius = 312 + 25 * sin(5 * angle + 0.5)
    let point = NSPoint(x: 512 + radius * cos(angle), y: 514 + radius * sin(angle))
    if index == 0 { blob.move(to: point) } else { blob.line(to: point) }
}
blob.close(); blob.fill()
NSColor.white.setFill()
NSBezierPath(roundedRect: NSRect(x: 411, y: 461, width: 57, height: 118), xRadius: 28, yRadius: 28).fill()
NSBezierPath(roundedRect: NSRect(x: 553, y: 461, width: 57, height: 118), xRadius: 28, yRadius: 28).fill()
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: target))
