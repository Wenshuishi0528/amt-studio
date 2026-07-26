import AMTStudioUI
import SwiftUI

@main
struct AMTStudioApplication: App {
  @StateObject private var model: AppModel

  init() {
    let arguments = CommandLine.arguments
    let initialProjectURL: URL?
    if let index = arguments.firstIndex(of: "--project"),
      arguments.indices.contains(index + 1)
    {
      initialProjectURL = URL(fileURLWithPath: arguments[index + 1])
    } else {
      initialProjectURL = nil
    }
    _model = StateObject(
      wrappedValue: AppModel(initialProjectURL: initialProjectURL)
    )
  }

  var body: some Scene {
    WindowGroup("AMT Studio") {
      ContentView(model: model)
    }
    .defaultSize(width: 1_360, height: 860)
  }
}
