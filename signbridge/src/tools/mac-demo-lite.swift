import AppKit
import Network
import WebKit

final class StaticServer {
    let root: URL
    var listener: NWListener?
    var port: UInt16 = 0
    init(root: URL) { self.root = root.resolvingSymlinksInPath() }
    static let types: [String: String] = ["html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "mjs": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "json": "application/json; charset=utf-8", "png": "image/png", "glb": "model/gltf-binary", "svg": "image/svg+xml", "wasm": "application/wasm"]
    func start() throws -> UInt16 {
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = NWEndpoint.hostPort(host: "127.0.0.1", port: .any)
        let l = try NWListener(using: parameters)
        let ready = DispatchSemaphore(value: 0)
        l.stateUpdateHandler = { state in
            switch state { case .ready, .failed: ready.signal(); default: break }
        }
        l.newConnectionHandler = { [weak self] connection in self?.handle(connection) }
        l.start(queue: .global())
        _ = ready.wait(timeout: .now() + 5)
        guard let value = l.port?.rawValue else { throw NSError(domain: "SignBridgeServe", code: 1) }
        listener = l; port = value
        return value
    }
    func reply(_ c: NWConnection, _ status: Int, _ type: String, _ body: Data, head: Bool) {
        let names = [200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed"]
        let header = "HTTP/1.1 \(status) \(names[status] ?? "Error")\r\nContent-Type: \(type)\r\nContent-Length: \(body.count)\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n"
        var out = Data(header.utf8)
        if !head { out.append(body) }
        c.send(content: out, completion: .contentProcessed { _ in c.cancel() })
    }
    func handle(_ c: NWConnection) {
        c.start(queue: .global())
        c.receive(minimumIncompleteLength: 1, maximumLength: 16384) { [weak self] data, _, _, _ in
            guard let self = self, let data = data, let text = String(data: data, encoding: .utf8) else { c.cancel(); return }
            let lines = text.components(separatedBy: "\r\n")
            let first = lines.first?.split(separator: " ").map(String.init) ?? []
            guard first.count >= 2, first[0] == "GET" || first[0] == "HEAD" else { return self.reply(c, 405, "text/plain", Data(), head: false) }
            let head = first[0] == "HEAD"
            let host = lines.dropFirst().first { $0.lowercased().hasPrefix("host:") }?.dropFirst(5).trimmingCharacters(in: .whitespaces)
            guard host == "127.0.0.1:\(self.port)" else { return self.reply(c, 403, "text/plain", Data(), head: head) }
            var path = first[1].split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? "/"
            path = path.removingPercentEncoding ?? ""
            if path == "/" { path = "/demo/index.html" }
            let parts = path.split(separator: "/", omittingEmptySubsequences: false).dropFirst()
            guard path.hasPrefix("/"), !path.unicodeScalars.contains(where: { $0.value == 92 || $0.value == 0 }), !parts.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }) else { return self.reply(c, 400, "text/plain", Data(), head: head) }
            let file = parts.reduce(self.root) { $0.appendingPathComponent(String($1)) }.resolvingSymlinksInPath()
            guard file.path.hasPrefix(self.root.path + "/") else { return self.reply(c, 403, "text/plain", Data(), head: head) }
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: file.path, isDirectory: &isDirectory), !isDirectory.boolValue, let body = try? Data(contentsOf: file) else { return self.reply(c, 404, "text/plain", Data(), head: head) }
            self.reply(c, 200, StaticServer.types[file.pathExtension.lowercased()] ?? "application/octet-stream", body, head: head)
        }
    }
}

final class LiteApp: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var server: StaticServer!
    var labels: [String: String] = [:]
    var status: NSTextField!
    var installButton: NSButton!
    var site: URL { Bundle.main.resourceURL!.appendingPathComponent("site", isDirectory: true) }
    func tr(_ key: String, _ fallback: String) -> String { labels[key] ?? fallback }
    func makeButton(_ title: String, _ action: Selector) -> NSButton {
        let value = NSButton(title: title, target: self, action: action)
        value.bezelStyle = .rounded; value.controlSize = .large; value.font = .systemFont(ofSize: 16)
        return value
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        if let data = try? Data(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("native-locales.json")),
           let value = try? JSONDecoder().decode([String: String].self, from: data) { labels = value }
        server = StaticServer(root: site)
        let web = WKWebView(frame: .zero)
        web.translatesAutoresizingMaskIntoConstraints = false
        installButton = makeButton(tr("nativeLiteInstallPlugin", "安装浏览器插件"), #selector(installExtension))
        let extensionsButton = makeButton(tr("nativeLiteOpenExtensions", "打开 Chrome 扩展页"), #selector(openExtensions))
        status = NSTextField(wrappingLabelWithString: "")
        status.font = .systemFont(ofSize: 15)
        let bar = NSStackView(views: [installButton, extensionsButton, status])
        bar.spacing = 12; bar.edgeInsets = NSEdgeInsets(top: 10, left: 16, bottom: 10, right: 16)
        bar.translatesAutoresizingMaskIntoConstraints = false
        let content = NSView()
        content.addSubview(bar); content.addSubview(web)
        NSLayoutConstraint.activate([
            bar.topAnchor.constraint(equalTo: content.topAnchor),
            bar.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            bar.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            web.topAnchor.constraint(equalTo: bar.bottomAnchor),
            web.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            web.bottomAnchor.constraint(equalTo: content.bottomAnchor)])
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 840), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "SignBridge 演示版"; window.contentView = content; window.center()
        do {
            let port = try server.start()
            web.load(URLRequest(url: URL(string: "http://127.0.0.1:" + String(port) + "/demo/index.html")!))
        } catch {
            status.stringValue = tr("nativeLiteStartFailed", "启动失败，请退出后重新打开。")
        }
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
    @objc func installExtension() {
        let panel = NSOpenPanel()
        panel.message = tr("nativeLiteInstallHelp", "请选择一个空文件夹"); panel.prompt = tr("nativeChoose", "选择此文件夹")
        panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = true; panel.allowsMultipleSelection = false
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Desktop", isDirectory: true)
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        installButton.isEnabled = false
        status.stringValue = tr("nativeWizardBusy", "正在校验并保存插件…")
        let source = site
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result: URL? = try? {
                let folder = try installPlugin(source: source, destination: destination)
                try savePluginDirectory(folder, settings: pluginSettingsFile())
                return folder
            }()
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.installButton.isEnabled = true
                if let folder = result {
                    NSWorkspace.shared.open(folder)
                    self.status.stringValue = self.tr("nativeLiteInstallDone", "插件已保存，文件夹已打开。")
                } else {
                    self.status.stringValue = self.tr("nativeWizardFailed", "所选位置不可用或含有其他文件，请选择空文件夹。")
                }
            }
        }
    }
    @objc func openExtensions() {
        guard let chrome = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.google.Chrome") else {
            status.stringValue = tr("nativeLiteChromeMissing", "没有找到 Chrome，请先安装 Chrome 浏览器。"); return
        }
        NSWorkspace.shared.open([URL(string: "chrome://extensions")!], withApplicationAt: chrome, configuration: NSWorkspace.OpenConfiguration())
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct LiteMain {
    static func main() {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--serve-only"), args.count > i + 1 {
            let s = StaticServer(root: URL(fileURLWithPath: args[i + 1], isDirectory: true))
            guard let p = try? s.start() else { exit(1) }
            print(p); fflush(stdout); RunLoop.main.run(); return
        }
        let app = NSApplication.shared; let d = LiteApp()
        app.setActivationPolicy(.regular); app.delegate = d
        withExtendedLifetime(d) { app.run() }
    }
}
