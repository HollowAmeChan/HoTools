void main()
{
    gl_Position=vec4(position,0.,1.);
    usingPos=position.xy*.5+vec2(.5,.5);//采样的uv
}