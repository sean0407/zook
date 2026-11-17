import AVFoundation
import SwiftUI

struct PairView: View {
    @EnvironmentObject var model: AppModel
    @State private var scanning = false
    @State private var working = false
    @State private var problem: String?

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "qrcode.viewfinder").font(.system(size: 56)).foregroundStyle(.tint)
            Text("配對你的 Mac").font(.title2.weight(.semibold))
            Text("在 Mac 的 Zook 打開「設定 → 遠端連線 → 配對新裝置」，再用這支 iPhone 掃描畫面上的 QR code。")
                .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center).padding(.horizontal, 28)
            if working { ProgressView("正在配對…") }
            else { Button { scanning = true } label: { Label("掃描 QR code", systemImage: "camera").frame(maxWidth: 240) }.buttonStyle(.borderedProminent).controlSize(.large) }
            if let problem = problem { Text(problem).font(.footnote).foregroundStyle(.red).multilineTextAlignment(.center).padding(.horizontal, 28) }
            Spacer()
            Text("對話只存在你的 Mac 上。這支 iPhone 和 Mac 之間的內容全程加密。").font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center).padding(.horizontal, 28).padding(.bottom, 12)
        }
        .sheet(isPresented: $scanning) {
            ScannerView { code in scanning = false; pair(code) }.ignoresSafeArea()
        }
        .onAppear { if let code = model.pendingCode { model.pendingCode = nil; pair(code) } }
        .onChange(of: model.pendingCode) { _, code in if let code = code { model.pendingCode = nil; pair(code) } }
    }

    private func pair(_ code: String) {
        guard !working else { return }
        working = true; problem = nil
        Task {
            do { try await model.pair(code: code) } catch { problem = error.localizedDescription }
            working = false
        }
    }
}

/// Camera view that reports the first Zook pairing QR code it sees.
struct ScannerView: UIViewControllerRepresentable {
    let onCode: (String) -> Void
    func makeUIViewController(context: Context) -> ScannerController { let c = ScannerController(); c.onCode = onCode; return c }
    func updateUIViewController(_ controller: ScannerController, context: Context) {}
}

final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?
    private let session = AVCaptureSession()
    private var done = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        let hint = UILabel(); hint.text = "對準 Mac 上的 QR code"; hint.textColor = .white; hint.font = .preferredFont(forTextStyle: .subheadline)
        hint.translatesAutoresizingMaskIntoConstraints = false
        guard let camera = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: camera), session.canAddInput(input) else {
            hint.text = "無法使用相機。請到「設定 → Zook」允許使用相機。"; hint.numberOfLines = 0; hint.textAlignment = .center
            view.addSubview(hint)
            NSLayoutConstraint.activate([hint.centerYAnchor.constraint(equalTo: view.centerYAnchor), hint.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24), hint.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24)])
            return
        }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        if session.canAddOutput(output) { session.addOutput(output); output.setMetadataObjectsDelegate(self, queue: .main); output.metadataObjectTypes = [.qr] }
        let preview = AVCaptureVideoPreviewLayer(session: session); preview.videoGravity = .resizeAspectFill; preview.frame = view.bounds
        view.layer.addSublayer(preview)
        view.addSubview(hint)
        NSLayoutConstraint.activate([hint.centerXAnchor.constraint(equalTo: view.centerXAnchor), hint.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -28)])
        DispatchQueue.global(qos: .userInitiated).async { self.session.startRunning() }
    }

    override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews(); view.layer.sublayers?.first { $0 is AVCaptureVideoPreviewLayer }?.frame = view.bounds }
    override func viewWillDisappear(_ animated: Bool) { super.viewWillDisappear(animated); session.stopRunning() }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !done, let code = (objects.first as? AVMetadataMachineReadableCodeObject)?.stringValue, code.hasPrefix("zook://pair") else { return }
        done = true; session.stopRunning(); onCode?(code)
    }
}
