import Foundation
import CryptoKit
import Darwin

private func pluginFailure() -> NSError {
    NSError(domain: "SignBridgePluginExport", code: 1)
}
private func pluginHash(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}
private func rejectPluginSymlinks(_ url: URL) throws {
    var path = url.path
    while path != "/" {
        var info = stat()
        let result = Darwin.lstat(path, &info)
        if result == 0 {
            if (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFLNK) { throw pluginFailure() }
        } else if errno != ENOENT && errno != ENOTDIR { throw pluginFailure() }
        path = (path as NSString).deletingLastPathComponent
    }
}
private func pluginMember(_ root: URL, _ name: String) throws -> URL {
    let parts = name.split(separator: "/", omittingEmptySubsequences: false)
    guard !parts.isEmpty, !name.contains("\\"), !name.contains("\0"),
          !parts.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }) else { throw pluginFailure() }
    let url = root.appendingPathComponent(name)
    try rejectPluginSymlinks(url)
    return url
}
private func verifyPlugin(_ root: URL, _ files: [String: String], _ buildData: Data) throws {
    try rejectPluginSymlinks(root)
    guard try Data(contentsOf: pluginMember(root, "BUILD.json")) == buildData else { throw pluginFailure() }
    for (name, digest) in files {
        let file = try pluginMember(root, name)
        guard pluginHash(try Data(contentsOf: file)) == digest else { throw pluginFailure() }
    }
}
// A user-selected directory is the extension root itself, not a parent to search.
func installPlugin(source: URL, destination: URL) throws -> URL {
    let manager = FileManager.default
    try rejectPluginSymlinks(source)
    let data = try Data(contentsOf: pluginMember(source, "BUILD.json"))
    guard let info = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          let files = info["files"] as? [String: String], !files.isEmpty,
          files["manifest.json"] != nil, files["demo/model.html"] != nil,
          files["BUILD.json"] == nil else { throw pluginFailure() }
    try verifyPlugin(source, files, data)
    try rejectPluginSymlinks(destination)
    var existedEmpty = false
    if manager.fileExists(atPath: destination.path) {
        let entries = try manager.contentsOfDirectory(atPath: destination.path)
        if !entries.isEmpty {
            try verifyPlugin(destination, files, data)
            return destination
        }
        existedEmpty = true
    }
    let parent = destination.deletingLastPathComponent()
    try manager.createDirectory(at: parent, withIntermediateDirectories: true)
    let stage = parent.appendingPathComponent(".signbridge-plugin-" + UUID().uuidString, isDirectory: true)
    try manager.createDirectory(at: stage, withIntermediateDirectories: false)
    defer { try? manager.removeItem(at: stage) }
    for name in files.keys.sorted() {
        let input = try pluginMember(source, name)
        let output = stage.appendingPathComponent(name)
        try manager.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(contentsOf: input).write(to: output)
        var fileInfo = stat()
        guard Darwin.lstat(input.path, &fileInfo) == 0,
              Darwin.chmod(output.path, fileInfo.st_mode & mode_t(0o777)) == 0 else { throw pluginFailure() }
    }
    try data.write(to: stage.appendingPathComponent("BUILD.json"), options: .atomic)
    try verifyPlugin(stage, files, data)
    if existedEmpty {
        guard try manager.contentsOfDirectory(atPath: destination.path).isEmpty else { throw pluginFailure() }
        guard Darwin.rmdir(destination.path) == 0 else { throw pluginFailure() } // Atomically refuses nonempty directories.
    }
    do { try manager.moveItem(at: stage, to: destination) }
    catch {
        if existedEmpty && !manager.fileExists(atPath: destination.path) { try? manager.createDirectory(at: destination, withIntermediateDirectories: false) }
        throw error
    }
    return destination
}

func pluginSettingsFile() throws -> URL {
    let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        .appendingPathComponent("SignBridge Demo", isDirectory: true)
    return support.appendingPathComponent("installation.json")
}
func savedPluginDirectory(settings: URL) throws -> URL? {
    try rejectPluginSymlinks(settings)
    guard FileManager.default.fileExists(atPath: settings.path) else { return nil }
    let data = try Data(contentsOf: settings)
    guard data.count <= 65536,
          let info = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          info["schema"] as? String == "signbridge-plugin-location-v1",
          let path = info["plugin_directory"] as? String, path.hasPrefix("/"), !path.contains("\0") else { throw pluginFailure() }
    return URL(fileURLWithPath: path, isDirectory: true)
}
func savePluginDirectory(_ directory: URL, settings: URL) throws {
    try rejectPluginSymlinks(settings)
    let data = try JSONSerialization.data(withJSONObject: ["schema": "signbridge-plugin-location-v1", "plugin_directory": directory.path], options: [.prettyPrinted, .sortedKeys])
    try FileManager.default.createDirectory(at: settings.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    try data.write(to: settings, options: .atomic)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: settings.path)
}
