import AppKit
import Foundation

final class DemoInstaller: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var pathLabel: NSTextField!
    var status: NSTextField!
    var continueButton: NSButton!
    var folderButton: NSButton!
    var chooseButton: NSButton!
    var labels: [String: String] = [:]
    var selected = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Desktop/SignBridge插件", isDirectory: true)
    var installedFolder: URL?
    var destinationChosen = false
    var root: URL { Bundle.main.resourceURL! }
    func tr(_ key: String) -> String { labels[key] ?? key }
    func button(_ key: String, _ action: Selector) -> NSButton {
        let value = NSButton(title: tr(key), target: self, action: action); value.bezelStyle = .rounded; return value
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        if let data = try? Data(contentsOf: root.appendingPathComponent("native-locales.json")),
           let value = try? JSONDecoder().decode([String: String].self, from: data) { labels = value }
        if let settings = try? pluginSettingsFile(), let saved = try? savedPluginDirectory(settings: settings) { selected = saved }
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 340), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = tr("nativeWizardTitle"); window.center()
        let title = NSTextField(labelWithString: tr("nativeWizardTitle")); title.font = .boldSystemFont(ofSize: 24)
        let lead = NSTextField(wrappingLabelWithString: tr("nativeWizardLead"))
        let label = NSTextField(labelWithString: tr("nativeWizardFolder")); label.font = .boldSystemFont(ofSize: 13)
        pathLabel = NSTextField(wrappingLabelWithString: selected.path); pathLabel.isSelectable = true
        pathLabel.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        chooseButton = button("nativeChooseInstaller", #selector(chooseFolder))
        let pathRow = NSStackView(views: [pathLabel, chooseButton]); pathRow.spacing = 14
        continueButton = button("nativeWizardContinue", #selector(install))
        folderButton = button("nativeWizardOpenFolder", #selector(openFolder)); folderButton.isEnabled = false
        let actions = NSStackView(views: [continueButton, folderButton]); actions.spacing = 12
        status = NSTextField(wrappingLabelWithString: "")
        let note = NSTextField(wrappingLabelWithString: tr("nativeWizardNote")); note.font = .systemFont(ofSize: 12); note.textColor = .secondaryLabelColor
        let stack = NSStackView(views: [title, lead, label, pathRow, actions, status, note]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false; window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 24),stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -24),stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 24),pathRow.widthAnchor.constraint(equalTo: stack.widthAnchor)])
        let menu = NSMenu(); let item = NSMenuItem(); menu.addItem(item); let submenu = NSMenu(); item.submenu = submenu
        let quit = NSMenuItem(title: tr("nativeQuitInstaller"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); quit.target = NSApp; submenu.addItem(quit); NSApp.mainMenu = menu
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
    @objc func chooseFolder() {
        let panel = NSOpenPanel(); panel.title = tr("nativeChoosePlugin"); panel.message = tr("nativeChoosePluginHelp"); panel.prompt = tr("nativeChoose")
        panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = true; panel.allowsMultipleSelection = false
        panel.directoryURL = selected.deletingLastPathComponent()
        guard panel.runModal() == .OK, let folder = panel.url else { return }
        selected = folder; destinationChosen = true; pathLabel.stringValue = folder.path; status.stringValue = ""; installedFolder = nil; folderButton.isEnabled = false; continueButton.title = tr("nativeWizardContinue")
    }
    @objc func install() {
        if installedFolder != nil {
            NSApp.terminate(nil)
            return
        }
        if !destinationChosen { chooseFolder(); guard destinationChosen else { return } }
        continueButton.isEnabled = false; chooseButton.isEnabled = false; status.stringValue = tr("nativeWizardBusy")
        let destination = selected
        let source = root.appendingPathComponent("chrome-extension", isDirectory: true)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do {
                let folder = try installPlugin(source: source, destination: destination)
                try savePluginDirectory(folder, settings: pluginSettingsFile())
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.installedFolder = folder; self.folderButton.isEnabled = true
                    self.status.stringValue = self.tr("nativeWizardReady")
                    self.continueButton.title = self.tr("nativeWizardFinish")
                    self.continueButton.isEnabled = true; self.chooseButton.isEnabled = true
                }
            } catch {
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.status.stringValue = self.tr("nativeWizardFailed")
                    self.continueButton.isEnabled = true; self.chooseButton.isEnabled = true
                }
            }
        }
    }
    @objc func openFolder() { if let folder = installedFolder { NSWorkspace.shared.open(folder) } }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
@main
struct InstallerMain {
    static func main() {
        let app = NSApplication.shared; let delegate = DemoInstaller()
        app.setActivationPolicy(.regular); app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
