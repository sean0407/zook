import SwiftUI
import UIKit

/// Message text the way iOS text normally behaves: press and hold to select a range, then copy, look up, translate or share.
struct SelectableText: UIViewRepresentable {
    let text: String
    var markdown = false

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false; view.isSelectable = true; view.isScrollEnabled = false
        view.backgroundColor = .clear
        view.textContainerInset = .zero; view.textContainer.lineFragmentPadding = 0
        view.adjustsFontForContentSizeCategory = true
        view.dataDetectorTypes = [.link]
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        view.setContentHuggingPriority(.required, for: .vertical)
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        // Only replace the text when it changed, so a selection survives the screen's regular refresh.
        guard context.coordinator.shown != text else { return }
        context.coordinator.shown = text
        view.attributedText = SelectableText.styled(text, markdown: markdown)
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        let width = proposal.width.flatMap { $0.isFinite && $0 > 0 ? $0 : nil } ?? UIScreen.main.bounds.width
        let fitted = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: min(ceil(fitted.width), width), height: ceil(fitted.height))
    }

    final class Coordinator { var shown: String? }

    /// Body text with inline bold, italic, code and links (the same subset the Mac shows inline).
    static func styled(_ text: String, markdown: Bool) -> NSAttributedString {
        let body = UIFont.preferredFont(forTextStyle: .body)
        let base: [NSAttributedString.Key: Any] = [.font: body, .foregroundColor: UIColor.label]
        guard markdown, let parsed = try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) else {
            return NSAttributedString(string: text, attributes: base)
        }
        let out = NSMutableAttributedString()
        for run in parsed.runs {
            var attributes = base
            let intent = run.inlinePresentationIntent ?? []
            var traits: UIFontDescriptor.SymbolicTraits = []
            if intent.contains(.stronglyEmphasized) { traits.insert(.traitBold) }
            if intent.contains(.emphasized) { traits.insert(.traitItalic) }
            if intent.contains(.code) {
                attributes[.font] = UIFontMetrics(forTextStyle: .body).scaledFont(for: .monospacedSystemFont(ofSize: body.pointSize * 0.92, weight: .regular))
                attributes[.backgroundColor] = UIColor.tertiarySystemFill
            } else if !traits.isEmpty, let descriptor = body.fontDescriptor.withSymbolicTraits(traits) {
                attributes[.font] = UIFont(descriptor: descriptor, size: 0)
            }
            if intent.contains(.strikethrough) { attributes[.strikethroughStyle] = NSUnderlineStyle.single.rawValue }
            if let link = run.link { attributes[.link] = link }
            out.append(NSAttributedString(string: String(parsed[run.range].characters), attributes: attributes))
        }
        return out
    }
}
