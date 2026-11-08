import Foundation
import CryptoKit

func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
let manager = FileManager.default
let root = manager.homeDirectoryForCurrentUser.appendingPathComponent("Library/Caches/SignBridgeExportTests/" + UUID().uuidString)
try manager.createDirectory(at: root, withIntermediateDirectories: true)
defer { try? manager.removeItem(at: root) }
func fixture(_ name: String) throws -> URL {
    let source = root.appendingPathComponent(name)
    try manager.createDirectory(at: source.appendingPathComponent("demo"), withIntermediateDirectories: true)
    let data = Data("{\"manifest_version\":3}".utf8)
    try data.write(to: source.appendingPathComponent("manifest.json"))
    let page = Data("<html>demo</html>".utf8)
    try page.write(to: source.appendingPathComponent("demo/model.html"))
    let info: [String: Any] = ["files": ["manifest.json": hash(data), "demo/model.html": hash(page)]]
    try JSONSerialization.data(withJSONObject: info, options: .sortedKeys).write(to: source.appendingPathComponent("BUILD.json"))
    try Data("must-not-copy".utf8).write(to: source.appendingPathComponent("unlisted-secret.txt"))
    return source
}
let source = try fixture("good")
let exported = try installPlugin(source: source, destination: root.appendingPathComponent("exports/chrome-extension"))
precondition(exported.lastPathComponent == "chrome-extension")
precondition(manager.fileExists(atPath: exported.appendingPathComponent("manifest.json").path))
precondition(!manager.fileExists(atPath: exported.appendingPathComponent("unlisted-secret.txt").path))
let reused = try installPlugin(source: source, destination: root.appendingPathComponent("exports/chrome-extension"))
precondition(reused.path == exported.path)
try Data("altered".utf8).write(to: exported.appendingPathComponent("manifest.json"))
do { _ = try installPlugin(source: source, destination: root.appendingPathComponent("exports/chrome-extension")); fatalError("Changed export accepted") } catch {}
let bad = try fixture("bad")
try manager.removeItem(at: bad.appendingPathComponent("demo"))
try manager.createSymbolicLink(at: bad.appendingPathComponent("demo"), withDestinationURL: source.appendingPathComponent("demo"))
do { _ = try installPlugin(source: bad, destination: root.appendingPathComponent("bad-exports")); fatalError("Symlink source accepted") } catch {}
let malicious = try fixture("traversal")
try JSONSerialization.data(withJSONObject: ["files": ["../outside": "a"]]).write(to: malicious.appendingPathComponent("BUILD.json"))
do { _ = try installPlugin(source: malicious, destination: root.appendingPathComponent("bad-paths")); fatalError("Traversal accepted") } catch {}
let symlinkDestination = root.appendingPathComponent("linked-export")
try manager.createSymbolicLink(at: symlinkDestination, withDestinationURL: root.appendingPathComponent("exports"))
do { _ = try installPlugin(source: source, destination: symlinkDestination); fatalError("Symlink target accepted") } catch {}
print("PASS: verified export, deterministic reuse, unlisted exclusion, tamper rejection, symlink and traversal rejection")
let custom = root.appendingPathComponent("我的插件")
let customResult = try installPlugin(source: source, destination: custom)
precondition(customResult.path == custom.path)
precondition(manager.fileExists(atPath: custom.appendingPathComponent("manifest.json").path))
precondition(!manager.fileExists(atPath: custom.appendingPathComponent("chrome-extension").path))
let customAgain = try installPlugin(source: source, destination: custom)
precondition(customAgain.path == custom.path)
let settings = root.appendingPathComponent("preferences/installation.json")
try savePluginDirectory(custom, settings: settings)
let saved = try savedPluginDirectory(settings: settings)
precondition(saved?.path == custom.path)
let empty = root.appendingPathComponent("新位置")
try manager.createDirectory(at: empty, withIntermediateDirectories: true)
let changed = try installPlugin(source: source, destination: empty)
try savePluginDirectory(changed, settings: settings)
let changedSaved = try savedPluginDirectory(settings: settings)
precondition(changedSaved?.path == changed.path)
precondition(manager.fileExists(atPath: custom.appendingPathComponent("manifest.json").path))
let personal = root.appendingPathComponent("有文件的目录")
try manager.createDirectory(at: personal, withIntermediateDirectories: true)
try Data("preserve".utf8).write(to: personal.appendingPathComponent("personal.txt"))
do { _ = try installPlugin(source: source, destination: personal); fatalError("Unrelated folder replaced") } catch {}
let personalContent = try String(contentsOf: personal.appendingPathComponent("personal.txt"), encoding: .utf8)
precondition(personalContent == "preserve")
print("PASS: exact custom directory, persisted selection, changed location and unrelated files preserved")

let metadataSymlink = root.appendingPathComponent("metadata-link")
_ = try installPlugin(source: source, destination: metadataSymlink)
try manager.removeItem(at: metadataSymlink.appendingPathComponent("BUILD.json"))
try manager.createSymbolicLink(at: metadataSymlink.appendingPathComponent("BUILD.json"), withDestinationURL: source.appendingPathComponent("BUILD.json"))
do { _ = try installPlugin(source: source, destination: metadataSymlink); fatalError("Linked build metadata accepted") } catch {}
print("PASS: exported BUILD.json symlink is rejected")
