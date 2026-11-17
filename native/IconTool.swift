// Renders the official icon of an installed app (or an icon file such as .icns/.svg) to a PNG.
// Usage: zook-icon <source.app|file> <out.png> [size]
import AppKit
let args = CommandLine.arguments
guard args.count >= 3 else { exit(2) }
let source = args[1], out = args[2], size = CGFloat(Int(args.count > 3 ? args[3] : "128") ?? 128)
let image: NSImage? = source.hasSuffix(".app") ? NSWorkspace.shared.icon(forFile: source) : NSImage(contentsOfFile: source)
guard let icon = image, let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { exit(1) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let box = NSRect(x: 0, y: 0, width: size, height: size)
// Keep the artwork's aspect ratio (SVG logos are rarely square).
let ratio = icon.size.width > 0 && icon.size.height > 0 ? icon.size.width / icon.size.height : 1
let draw = ratio >= 1 ? NSRect(x: 0, y: (size - size / ratio) / 2, width: size, height: size / ratio) : NSRect(x: (size - size * ratio) / 2, y: 0, width: size * ratio, height: size)
icon.draw(in: source.hasSuffix(".app") ? box : draw.insetBy(dx: size * 0.08, dy: size * 0.08), from: .zero, operation: .sourceOver, fraction: 1)
NSGraphicsContext.restoreGraphicsState()
guard let data = rep.representation(using: .png, properties: [:]) else { exit(1) }
do { try data.write(to: URL(fileURLWithPath: out), options: .atomic) } catch { exit(1) }
