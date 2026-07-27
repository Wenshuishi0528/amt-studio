import SwiftUI

public enum AMTAppearanceMode: String, CaseIterable, Identifiable, Sendable {
  case precision
  case spectrum

  public var id: String { rawValue }

  public var label: String {
    switch self {
    case .precision: "精密模式"
    case .spectrum: "炫酷模式"
    }
  }

  public var detail: String {
    switch self {
    case .precision:
      "克制的石墨灰与青绿色，信息清楚，适合长时间工作。"
    case .spectrum:
      "更深的午夜背景与蓝紫光谱，仅增强视觉，不改变识别结果。"
    }
  }
}

struct AMTTheme {
  let mode: AMTAppearanceMode

  var canvas: Color {
    switch mode {
    case .precision: Color(red: 0.050, green: 0.064, blue: 0.073)
    case .spectrum: Color(red: 0.025, green: 0.032, blue: 0.071)
    }
  }

  var sidebar: Color {
    switch mode {
    case .precision: Color(red: 0.063, green: 0.080, blue: 0.090)
    case .spectrum: Color(red: 0.031, green: 0.042, blue: 0.091)
    }
  }

  var surface: Color {
    switch mode {
    case .precision: Color(red: 0.086, green: 0.105, blue: 0.116)
    case .spectrum: Color(red: 0.047, green: 0.061, blue: 0.125)
    }
  }

  var raisedSurface: Color {
    switch mode {
    case .precision: Color(red: 0.105, green: 0.129, blue: 0.141)
    case .spectrum: Color(red: 0.063, green: 0.082, blue: 0.160)
    }
  }

  var border: Color {
    switch mode {
    case .precision: Color.white.opacity(0.10)
    case .spectrum: Color(red: 0.235, green: 0.650, blue: 0.930).opacity(0.24)
    }
  }

  var accent: Color {
    switch mode {
    case .precision: Color(red: 0.239, green: 0.816, blue: 0.737)
    case .spectrum: Color(red: 0.188, green: 0.780, blue: 1.000)
    }
  }

  var active: Color {
    switch mode {
    case .precision: Color(red: 0.682, green: 0.918, blue: 0.318)
    case .spectrum: Color(red: 0.588, green: 0.416, blue: 1.000)
    }
  }

  var mutedText: Color {
    Color.white.opacity(0.56)
  }

  var quietText: Color {
    Color.white.opacity(0.38)
  }

  var accentGradient: LinearGradient {
    LinearGradient(
      colors: mode == .precision
        ? [accent, Color(red: 0.375, green: 0.882, blue: 0.610)]
        : [accent, active],
      startPoint: .leading,
      endPoint: .trailing
    )
  }

  var canvasGradient: LinearGradient {
    LinearGradient(
      colors: mode == .precision
        ? [canvas, Color(red: 0.059, green: 0.078, blue: 0.084)]
        : [canvas, Color(red: 0.043, green: 0.035, blue: 0.118)],
      startPoint: .topLeading,
      endPoint: .bottomTrailing
    )
  }
}
