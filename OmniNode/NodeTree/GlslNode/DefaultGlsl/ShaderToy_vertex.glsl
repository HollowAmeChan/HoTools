//-------------------------------------------------
//            ShaderToy适配vertex_shader
#version 330 core
layout(location=0)in vec3 aPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

//shadertoy
out vec2 fragCoord;
uniform float iTime;
uniform vec3 iResolution;
uniform vec4 iMouse;
uniform float iFrame;

void main()
{
    gl_Position=projection*view*model*vec4(aPos,1.);
    vec4 temp=gl_Position/gl_Position.w;
    vec2 temp2=temp.xy*iResolution.xy;//中心为原点中心为原点的屏幕坐标
    fragCoord=temp2+iResolution.xy*.5;
}
