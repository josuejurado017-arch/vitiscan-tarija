import onnx
from onnx import helper, TensorProto
import numpy as np

def create_vitiscan_onnx_model(output_path: str):
    """
    Crea un modelo ONNX ligero para clasificación de viñedos:
    Clases: [0: Sano, 1: Estrés Hídrico Severo, 2: Brote Lobesia Botrana]
    Input: [1, 3, 224, 224] (Float32 NCHW)
    Output: [1, 3] (Float32 Softmax Logits)
    """
    input_tensor = helper.make_tensor_value_info('input', TensorProto.FLOAT, [1, 3, 224, 224])
    output_tensor = helper.make_tensor_value_info('output', TensorProto.FLOAT, [1, 3])

    np.random.seed(42)
    conv1_w = np.random.randn(8, 3, 3, 3).astype(np.float32) * 0.1
    conv1_w[0, 1, :, :] += 0.5  # Canal verde (G)
    conv1_w[1, 0, :, :] += 0.4  # Canal rojo (R)
    conv1_w[2, 2, :, :] += 0.3  # Canal azul (B)
    conv1_b = np.zeros(8, dtype=np.float32)

    conv1_w_tensor = helper.make_tensor('conv1_w', TensorProto.FLOAT, [8, 3, 3, 3], conv1_w.flatten())
    conv1_b_tensor = helper.make_tensor('conv1_b', TensorProto.FLOAT, [8], conv1_b)

    fc_w = np.array([
        [1.8, -0.6, -0.5],
        [-0.8, 2.1, -0.4],
        [-0.4, -0.7, 1.9],
        [0.2, -0.1, 0.3],
        [-0.1, 0.4, -0.2],
        [0.3, 0.1, -0.1],
        [-0.2, 0.3, 0.1],
        [0.1, -0.2, 0.4]
    ], dtype=np.float32)
    fc_b = np.array([0.1, -0.1, -0.2], dtype=np.float32)

    fc_w_tensor = helper.make_tensor('fc_w', TensorProto.FLOAT, [8, 3], fc_w.flatten())
    fc_b_tensor = helper.make_tensor('fc_b', TensorProto.FLOAT, [3], fc_b)

    node_conv = helper.make_node(
        'Conv',
        inputs=['input', 'conv1_w', 'conv1_b'],
        outputs=['conv_out'],
        kernel_shape=[3, 3],
        pads=[1, 1, 1, 1]
    )

    node_relu = helper.make_node('Relu', inputs=['conv_out'], outputs=['relu_out'])
    node_pool = helper.make_node('GlobalAveragePool', inputs=['relu_out'], outputs=['pool_out'])
    node_flatten = helper.make_node('Flatten', inputs=['pool_out'], outputs=['flat_out'], axis=1)
    node_gemm = helper.make_node('Gemm', inputs=['flat_out', 'fc_w', 'fc_b'], outputs=['logits'], alpha=1.0, beta=1.0)
    node_softmax = helper.make_node('Softmax', inputs=['logits'], outputs=['output'], axis=1)

    graph = helper.make_graph(
        nodes=[node_conv, node_relu, node_pool, node_flatten, node_gemm, node_softmax],
        name='VitiScanTarijaClassifier',
        inputs=[input_tensor],
        outputs=[output_tensor],
        initializer=[conv1_w_tensor, conv1_b_tensor, fc_w_tensor, fc_b_tensor]
    )

    # Compatible con ONNX Runtime: ir_version=9 / 10, opset 17
    opset = helper.make_opsetid("", 17)
    model = helper.make_model(
        graph,
        producer_name='VitiScan-Tarija-EdgeAI',
        opset_imports=[opset],
        ir_version=9
    )

    onnx.checker.check_model(model)
    onnx.save(model, output_path)
    print(f"Modelo ONNX generado con éxito en: {output_path} (IR v9, Opset 17)")

if __name__ == '__main__':
    create_vitiscan_onnx_model('ai-service/models/vitiscan_resnet_detector.onnx')
