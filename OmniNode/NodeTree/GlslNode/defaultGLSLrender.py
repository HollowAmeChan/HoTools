import numpy as np

vertices = np.array([
    # positions
    -0.5, -0.5, -0.5,
    0.5, -0.5, -0.5,
    0.5,  0.5, -0.5,
    -0.5,  0.5, -0.5,

    -0.5, -0.5,  0.5,
    0.5, -0.5,  0.5,
    0.5,  0.5,  0.5,
    -0.5,  0.5,  0.5
], dtype=np.float32)
# 顶点数据

indices = np.array([
    # 右面
    1, 5, 6,
    6, 2, 1,
    # 左面
    4, 0, 3,
    7, 4, 3,
    # 顶面
    3, 2, 6,
    3, 6, 7,
    # 底面
    4, 5, 1,
    1, 0, 4,
    # 后面
    4, 6, 5,
    4, 7, 6,
    # 前面
    0, 2, 1,
    2, 3, 0,
], dtype=np.uint32)

vertex_shader = """
#version 330 core
layout (location = 0) in vec3 aPos;
out vec3 worldPos; //输出世界坐标

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

void main()
{
gl_Position = projection * view * model * vec4(aPos, 1.0);
worldPos = vec3(model * vec4(aPos, 1.0)); 
}
"""

fragment_shader = """
#version 330 core
in vec3 worldPos;//传入世界坐标
out vec4 FragColor;
void main()
{
//FragColor = vec4(1.0f, 1.0f, 1.0f, 1.0f);
FragColor = vec4(worldPos.x, worldPos.y, worldPos.z, 1.0);// 坐标颜色
}
"""
