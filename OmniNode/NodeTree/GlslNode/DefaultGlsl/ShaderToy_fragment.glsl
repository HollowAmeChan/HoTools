#version 330 core
out vec4 FragColor;

uniform vec3 iResolution;
uniform float iTime;
uniform vec4 iMouse;
uniform float iFrame;
in vec2 fragCoord;
//-------------------------------------------------
//            ShaderToy适配vertex_shader
//          将fragColor全部替换为FragColor
//          将mainImage函数传入参数全部删除
//              将mainImage替换为main
//-------------------------------------------------
//↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓