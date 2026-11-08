import AppKit
import Foundation
import Darwin

final class DemoApp: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var status: NSTextField!
    var address: NSTextField!
    var openButton: NSButton!
    var child: Process?
    var logHandle: FileHandle?
    var poller: Timer?
    var signalSources: [DispatchSourceSignal] = []
    var closing = false
    var started = Date()
    var serviceURL: URL?
    var stateURL: URL!
    var logURL: URL!
    var labels: [String: String] = [:]
    var root: URL { Bundle.main.resourceURL! }
    func tr(_ key: String) -> String { labels[key] ?? key }
    func button(_ title: String, _ action: Selector) -> NSButton {
        let b = NSButton(title: tr(title), target: self, action: action)
        b.bezelStyle = .rounded
        return b
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            labels = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: root.appendingPathComponent("native-locales.json")))
            NSApp.applicationIconImage = NSImage(contentsOf: root.appendingPathComponent("chrome-extension/icons/icon128.png"))
            let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true).appendingPathComponent("SignBridge Demo", isDirectory: true)
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let id = UUID().uuidString
            stateURL = support.appendingPathComponent("run-\(id).json")
            logURL = support.appendingPathComponent("service-\(id).log")
            makeWindow()
            FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
            logHandle = try FileHandle(forWritingTo: logURL)
            let process = Process()
            process.executableURL = root.appendingPathComponent("runtime/bin/python3.10")
            process.arguments = ["-I", "-B", root.appendingPathComponent("tools/sign-native-model-serve.py").path,
                                 "--config", root.appendingPathComponent("model-config.json").path,
                                 "--state-file", stateURL.path, "--parent-pid", String(getpid())]
            process.currentDirectoryURL = root
            var environment = ProcessInfo.processInfo.environment
            for key in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"] { environment.removeValue(forKey: key) }
            environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            environment["HF_HUB_OFFLINE"] = "1"
            environment["TRANSFORMERS_OFFLINE"] = "1"
            environment["TOKENIZERS_PARALLELISM"] = "false"
            process.environment = environment
            process.standardOutput = logHandle
            process.standardError = logHandle
            child = process
            try process.run()
            for value in [SIGTERM, SIGINT] {
                signal(value, SIG_IGN)
                let source = DispatchSource.makeSignalSource(signal: value, queue: .main)
                source.setEventHandler { NSApp.terminate(nil) }
                source.resume(); signalSources.append(source)
            }
            process.terminationHandler = { [weak self] _ in DispatchQueue.main.async {
                guard let self = self, !self.closing else { return }
                self.serviceURL = nil; self.openButton.isEnabled = false; self.status.stringValue = self.tr("nativeFailed")
            } }
            started = Date()
            poller = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in self?.poll() }
        } catch {
            if window == nil { makeWindow() }
            status.stringValue = tr("nativeFailed")
            if let logHandle = logHandle { try? logHandle.write(contentsOf: Data("Native launch failed\n".utf8)) }
        }
    }
    func makeWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 600, height: 260), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = tr("nativeTitle")
        let menu = NSMenu(); let item = NSMenuItem(); menu.addItem(item)
        let applicationMenu = NSMenu(); item.submenu = applicationMenu
        let open = NSMenuItem(title: tr("nativeOpen"), action: #selector(openDemo), keyEquivalent: "o"); open.target = self
        applicationMenu.addItem(open); applicationMenu.addItem(.separator())
        let quitItem = NSMenuItem(title: tr("nativeQuit"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); quitItem.target = NSApp
        applicationMenu.addItem(quitItem); NSApp.mainMenu = menu
        window.center()
        let heading = NSTextField(labelWithString: tr("nativeTitle")); heading.font = .boldSystemFont(ofSize: 24)
        status = NSTextField(wrappingLabelWithString: tr("nativeLoading"))
        address = NSTextField(labelWithString: "")
        address.isSelectable = true; address.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        let note = NSTextField(wrappingLabelWithString: tr("nativeNote")); note.textColor = .secondaryLabelColor; note.font = .systemFont(ofSize: 12)
        openButton = button("nativeOpen", #selector(openDemo)); openButton.isEnabled = false
        let row = NSStackView(views: [openButton, button("nativePlugin", #selector(openPlugin)), button("nativeLog", #selector(openLog)), button("nativeQuit", #selector(quit))]); row.spacing = 8
        let stack = NSStackView(views: [heading, status, address, row, note]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 24), stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -24), stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 24)])
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func poll() {
        guard let process = child else { return }
        if !process.isRunning || Date().timeIntervalSince(started) > 90 {
            poller?.invalidate(); serviceURL = nil; openButton.isEnabled = false; if process.isRunning { process.terminate() }; status.stringValue = tr("nativeFailed"); return
        }
        guard let bytes = try? Data(contentsOf: stateURL), let state = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              let pid = state["pid"] as? Int, pid == Int(process.processIdentifier),
              let parent = state["parent_pid"] as? Int, parent == Int(getpid()),
              state["checkpoint_sha256"] as? String == "c6997e70392afac6748999e2e311131e7c2d0928b06da6ee97b184ef13e8af2d",
              let text = state["url"] as? String, let url = URL(string: text), url.scheme == "http", url.host == "127.0.0.1", let port = url.port, port > 0, port <= 65535,
              url.path == "/demo/model.html", url.query == nil, url.fragment == nil, url.user == nil, url.password == nil else { return }
        serviceURL = url
        poller?.invalidate()
        openButton.isEnabled = true
        status.stringValue = tr("nativeReady")
        address.stringValue = "http://127.0.0.1:\(port)"
        if !CommandLine.arguments.contains("--no-open") { openDemo() }
    }
    @objc func openDemo() { guard let process = child, process.isRunning, let url = serviceURL else { return }; NSWorkspace.shared.open(url) }
    @objc func openLog() { if let url = logURL { NSWorkspace.shared.activateFileViewerSelecting([url]) } }
    @objc func openPlugin() {
        let url = root.appendingPathComponent("chrome-extension", isDirectory: true)
        NSWorkspace.shared.activateFileViewerSelecting([url])
        let alert = NSAlert(); alert.messageText = tr("nativeTitle"); alert.informativeText = tr("nativePluginGuide") + "\n" + (address?.stringValue ?? "http://127.0.0.1:8787") + "\n\n" + url.path
        alert.addButton(withTitle: tr("nativeOK")); alert.runModal()
    }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { window.makeKeyAndOrderFront(nil); if serviceURL != nil { openDemo() }; return true }
    func applicationWillTerminate(_ notification: Notification) {
        closing = true
        poller?.invalidate()
        if let process = child, process.isRunning {
            process.terminate()
            let deadline = Date().addingTimeInterval(3)
            while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
            process.waitUntilExit()
        }
        try? logHandle?.close()
    }
}
let app = NSApplication.shared
let delegate = DemoApp()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
