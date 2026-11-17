import SwiftUI

/// The same Bot faces as on the Mac: a coloured shape with two eyes. The shape numbers match the Mac app.
enum BotLook {
    static let shapeCount = 13
    static let colors = ["#111111", "#a47545", "#ff284b", "#ff6d0c", "#f59a0a", "#13bf78", "#14b8a6", "#2585f6", "#9254ff", "#ed2f9b", "#959595"]

    static func index(_ shape: String?) -> Int {
        switch shape { case "circle": return 1; case "square": return 9; case "triangle": return 4; default: break }
        let digits = (shape ?? "0").filter(\.isNumber)
        return (Int(digits) ?? 0) % shapeCount
    }

    /// Corner points of the angular shapes, in percent of the box (same numbers as the Mac's stylesheet).
    static let polygons: [Int: [(CGFloat, CGFloat)]] = [
        3: [(50, 0), (63, 32), (98, 35), (72, 57), (80, 92), (50, 72), (20, 92), (28, 57), (2, 35), (37, 32)],
        4: [(50, 2), (98, 90), (2, 90)],
        5: [(25, 4), (75, 4), (100, 50), (75, 96), (25, 96), (0, 50)],
        6: [(50, 0), (62, 25), (90, 10), (75, 38), (100, 50), (75, 62), (90, 90), (62, 75), (50, 100), (38, 75), (10, 90), (25, 62), (0, 50), (25, 38), (10, 10), (38, 25)],
        7: [(50, 0), (100, 50), (50, 100), (0, 50)],
        8: [(50, 96), (5, 54), (2, 30), (14, 12), (33, 10), (50, 27), (67, 10), (86, 12), (98, 30), (95, 54)],
        10: [(20, 0), (80, 0), (100, 20), (100, 80), (80, 100), (20, 100), (0, 80), (0, 20)],
        11: [(50, 0), (62, 20), (85, 15), (80, 38), (100, 50), (80, 62), (85, 85), (62, 80), (50, 100), (38, 80), (15, 85), (20, 62), (0, 50), (20, 38), (15, 15), (38, 20)],
        12: [(50, 0), (95, 25), (95, 75), (50, 100), (5, 75), (5, 25)],
    ]

    /// Corner roundness of the soft shapes, in percent: top-left, top-right, bottom-right, bottom-left.
    static let corners: [Int: (CGFloat, CGFloat, CGFloat, CGFloat)] = [0: (36, 50, 41, 48), 1: (50, 50, 50, 50), 2: (22, 45, 24, 45), 9: (22, 22, 22, 22)]
}

struct BotShape: Shape {
    let index: Int

    func path(in rect: CGRect) -> Path {
        if let points = BotLook.polygons[index] {
            var path = Path()
            for (i, p) in points.enumerated() {
                let point = CGPoint(x: rect.minX + rect.width * p.0 / 100, y: rect.minY + rect.height * p.1 / 100)
                if i == 0 { path.move(to: point) } else { path.addLine(to: point) }
            }
            path.closeSubpath()
            return path
        }
        let c = BotLook.corners[index] ?? BotLook.corners[0]!
        let side = min(rect.width, rect.height)
        return UnevenRoundedRectangle(topLeadingRadius: side * c.0 / 100, bottomLeadingRadius: side * c.3 / 100, bottomTrailingRadius: side * c.2 / 100, topTrailingRadius: side * c.1 / 100, style: .continuous).path(in: rect)
    }
}

struct BotAvatar: View {
    let color: String?, shape: String?
    var size: CGFloat = 44

    var body: some View {
        BotShape(index: BotLook.index(shape))
            .fill(Color(hex: color) ?? Color(red: 0.94, green: 0.51, blue: 0.36))
            .rotationEffect(.degrees(-7))
            .frame(width: size, height: size)
            .overlay(HStack(spacing: size * 0.085) {
                Capsule().fill(.white).frame(width: size * 0.085, height: size * 0.14)
                Capsule().fill(.white).frame(width: size * 0.085, height: size * 0.14)
            })
            .accessibilityHidden(true)
    }
}

/// A group's picture: up to three of its members, overlapped, and how many more there are.
struct GroupAvatar: View {
    let members: [BotSummary], extra: Int
    var size: CGFloat = 44

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach(Array(members.prefix(3).enumerated()), id: \.offset) { i, bot in
                BotAvatar(color: bot.color, shape: bot.shape, size: size * 0.58)
                    .offset(x: [0, size * 0.42, 0][i], y: [0, 0, size * 0.42][i])
            }
            if extra > 0 {
                Text("+\(extra)").font(.system(size: size * 0.3, weight: .semibold)).foregroundStyle(.secondary)
                    .frame(width: size * 0.58, height: size * 0.58).offset(x: size * 0.42, y: size * 0.42)
            }
        }
        .frame(width: size, height: size, alignment: .topLeading)
        .accessibilityHidden(true)
    }
}

enum Haptics {
    /// A light tap, unless the user turned 觸感反饋 off in settings.
    static func tap() {
        guard UserDefaults.standard.object(forKey: "haptics") as? Bool ?? true else { return }
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }
}
