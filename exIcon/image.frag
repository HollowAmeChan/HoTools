void main()
{
    vec2 uv=usingPos*viewSize/200/iconSize;
    vec4 texColor=texture(tex,uv);
    if(uv.x<0.||uv.x>1.||uv.y<0.||uv.y>1.){
        texColor.a=0.;// 超出范围的像素 alpha 设为 0
    }
    texColor.rgb=pow(texColor.rgb,vec3(1/2.2));// gamma校正
    FragColor=vec4(texColor.rgb,texColor.a*iconAlpha);
    
    // FragColor.xy*=viewSize;//防止接口消失
    // FragColor.xy/=viewSize;
}