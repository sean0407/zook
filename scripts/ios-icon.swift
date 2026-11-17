// Makes the iOS app icon from the Mac artwork: an opaque 1024px square (iOS rounds the corners itself).
import AppKit
import ImageIO
import UniformTypeIdentifiers
let args = CommandLine.arguments
guard args.count == 3, let source = NSImage(contentsOfFile: args[1]), let cg = source.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fatalError("usage: ios-icon <source.png> <out.png>") }
let size = 1024
// The tile colour, read just inside the middle of the artwork's top edge, fills what its rounded corners leave empty.
let tile = NSBitmapImageRep(cgImage: cg).colorAt(x: cg.width / 2, y: Int(Double(cg.height) * 0.03))?.usingColorSpace(.sRGB) ?? NSColor(srgbRed: 0.95, green: 0.95, blue: 0.96, alpha: 1)
let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
context.setFillColor(red: tile.redComponent, green: tile.greenComponent, blue: tile.blueComponent, alpha: 1)
context.fill(CGRect(x: 0, y: 0, width: size, height: size))
context.interpolationQuality = .high
// Drawn slightly larger so the artwork's own rounded corners fall outside the mask iOS applies.
context.draw(cg, in: CGRect(x: -16, y: -16, width: size + 32, height: size + 32))
let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: args[2]) as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(destination, context.makeImage()!, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("cannot write icon") }
