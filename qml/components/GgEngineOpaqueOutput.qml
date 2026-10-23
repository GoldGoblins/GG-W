import QtQuick
import QtQuick3D
Effect {
    passes: Pass {
        shaders: Shader { stage: Shader.Fragment;shader:Qt.resolvedUrl("../shaders/gg-engine-output.frag") }
    }
}
