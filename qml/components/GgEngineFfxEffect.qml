import QtQuick
import QtQuick3D

// Original quarter-resolution Box4/Gauss4 and gamma-byte combine, adapted to
// Qt's public multi-pass Effect API. Only two quarter buffers stay live.
Effect {
    property real glowWeight: 0
    property real hazeWeight: 0
    property bool ghost: false
    property bool underwaterWave: false
    property real timeSeconds: 0
    property bool gammaInput: true
    property bool opaqueOutput: true
    property var waveTexture: null
    property real viewportWidth: 128
    property real viewportHeight: 128
    property real filterAxis: 0
    property TextureInput blurTexture: TextureInput {}
    property TextureInput waveLut: TextureInput {
        texture: Texture {
            textureData: waveTexture
            tilingModeHorizontal: Texture.Repeat
            tilingModeVertical: Texture.Repeat
            minFilter: Texture.Linear
            magFilter: Texture.Linear
            generateMipmaps: false
        }
    }
    Buffer {
        id: quarterA;name: "engineQuarterA";format:Buffer.RGBA16F
        sizeMultiplier: Math.max(.25,8/Math.max(1,viewportWidth),8/Math.max(1,viewportHeight))
    }
    Buffer {
        id: quarterB;name: "engineQuarterB";format:Buffer.RGBA16F
        sizeMultiplier: quarterA.sizeMultiplier
    }
    passes: [
        Pass {
            output:quarterA
            shaders:Shader {stage:Shader.Fragment;shader:Qt.resolvedUrl("../shaders/gg-engine-ffx-down.frag")}
        },
        Pass {
            output:quarterB
            commands:[BufferInput {buffer:quarterA},SetUniformValue {target:"filterAxis";value:0}]
            shaders:Shader {stage:Shader.Fragment;shader:Qt.resolvedUrl("../shaders/gg-engine-ffx-gauss.frag")}
        },
        Pass {
            output:quarterA
            commands:[BufferInput {buffer:quarterB},SetUniformValue {target:"filterAxis";value:1}]
            shaders:Shader {stage:Shader.Fragment;shader:Qt.resolvedUrl("../shaders/gg-engine-ffx-gauss.frag")}
        },
        Pass {
            commands:BufferInput {buffer:quarterA;sampler:"blurTexture"}
            shaders:Shader {stage:Shader.Fragment;shader:Qt.resolvedUrl("../shaders/gg-engine-ffx-combine.frag")}
        }
    ]
}
