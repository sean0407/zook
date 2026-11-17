// Fits a square artwork into the macOS app-icon grid: 824px rounded square centered on a transparent 1024px canvas.
import AppKit
let args = CommandLine.arguments
guard args.count == 3, let source = NSImage(contentsOfFile: args[1]) else { fatalError("usage: fit-icon <source.png> <out.png>") }
let size = 1024, inset: CGFloat = 100, side: CGFloat = 824
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let rect = NSRect(x: inset, y: inset, width: side, height: side)
NSBezierPath(roundedRect: rect, xRadius: 185, yRadius: 185).addClip()
// Trim the artwork's own outer margin (its rounded corners) so only the tile fills the clip.
let crop: CGFloat = 0.012
let src = NSRect(x: source.size.width * crop, y: source.size.height * crop, width: source.size.width * (1 - 2 * crop), height: source.size.height * (1 - 2 * crop))
source.draw(in: rect, from: src, operation: .copy, fraction: 1)
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
